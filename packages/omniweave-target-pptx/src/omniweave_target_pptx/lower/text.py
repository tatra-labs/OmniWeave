"""`lower.text`: a `<text>` as one text box, each positioned line a paragraph. D797.

09 section 12.1. The lines are `textlines`', the model `measure.py` shapes, so the compiler's
lines are the checker's (OUT2). The compile reads no font: a box's place is a function of the IL
alone (section 6), so nothing here measures a glyph.

- **The box** has `wrap="none"`, no insets and no autofit, so DrawingML lays each paragraph on one
  line and aligns it in the box. `text-anchor` is `algn`, and the box's left edge (`start`),
  centre (`middle`) or right edge (`end`) is the text's `x`. The text sits where the anchor puts
  it whatever the box's width, so the width is a nominal frame: `NOMINAL_ADVANCE` em a character
  of the widest line, plus its letter spacing.
- **The lines.** A line's baseline is its `y`, else the line before's, plus its `dy`, and
  `pptx.text.lines@1` holds each below the last. Each paragraph's line spacing is exact: the
  first's is `LEADING` em of its size, each later one's its distance from the baseline before, in
  points. The box's top is the first baseline less `ASCENT` of the first line's spacing, and its
  height is the spacings summed. A face whose ascent is not the model's moves its text by the
  difference: the model is a constant because the compile reads no face.
- **The runs.** Each run is an `a:r` with its owner's properties, inherited. `sz` and `spc` are
  px x 75, the font rule's hundredths of a point. `b` is a weight of 600 or more, CSS's own line
  between a light and a bold face. `i` is `italic`, `u` and `strike` are `text-decoration`, and
  `baseline` is 30% up for `super` and 25% down for `sub`, PowerPoint's own. A run's fill and line
  are the shape families' paint (`lower.paint`, `lower.stroke`). Its face is the first family the
  stack names that is not a CSS generic, as `a:latin`, `a:ea` and `a:cs`; a stack of generics
  alone takes the theme's face. `lang` is the Brief's primary language.
- **A matrix** moves and turns the box as `_geometry.place` does a preset's, and grows each size,
  spacing and line by its scale.
"""

from __future__ import annotations

from collections.abc import Iterator
from itertools import pairwise
from typing import TYPE_CHECKING, Any, Final

from omniweave_core.errors import TargetError

from omniweave_target_pptx.lower import paint, stroke
from omniweave_target_pptx.lower._emit import xfrm
from omniweave_target_pptx.lower._geometry import emu, place
from omniweave_target_pptx.lower._style import element
from omniweave_target_pptx.lower.geometry import offset
from omniweave_target_pptx.lower.ids import shape_name
from omniweave_target_pptx.lower.transform import transform
from omniweave_target_pptx.textlines import (
    TSPAN,
    Line,
    inherited,
    length,
    lines,
    preserved,
    style,
)

if TYPE_CHECKING:
    from omniweave_core.out.carrier import CarrierNode

    from omniweave_target_pptx.lower._emit import Emitter
    from omniweave_target_pptx.lower._style import Chain

__all__ = [
    "anchor",
    "baseline",
    "decoration",
    "italic",
    "run",
    "shift",
    "size",
    "spacing",
    "text_box",
    "typeface",
    "weight",
    "whitespace",
]

HUNDREDTHS: Final = 75
"""A user unit, a CSS px, is 0.75 pt: hundredths of a point a unit, the font rule's `sz`."""
ASCENT: Final = 0.8
"""Where a line's baseline sits in its exact spacing, from the top."""
LEADING: Final = 1.2
"""The first line's spacing, in em: CSS's `normal`, near enough, for a line with none before."""
NOMINAL_ADVANCE: Final = 0.6
"""The frame's width a character, in em. The text's place does not depend on it."""
BOLD_FROM: Final = 600
SUPER: Final = 30000
SUB: Final = -25000
ALIGN: Final = {"start": "l", "middle": "ctr", "end": "r"}
GENERIC: Final = frozenset(
    {
        "cursive",
        "emoji",
        "fangsong",
        "fantasy",
        "math",
        "monospace",
        "sans-serif",
        "serif",
        "system-ui",
        "ui-monospace",
        "ui-rounded",
        "ui-sans-serif",
        "ui-serif",
    }
)
_SHARE: Final = {"start": 0.0, "middle": 0.5, "end": 1.0}
"""How much of the frame's width lies before `x`."""


def text_box(em: Emitter, node: CarrierNode, chain: Chain) -> None:
    """A `<text>` as one `p:sp` text box (module docstring)."""
    nodes = list(_chains(node, chain))
    for n, _ in nodes:
        shift(n)  # a `dx` anywhere in the text is refused, as the gate refuses it
    chains = {id(n): c for n, c in nodes}
    found = lines(node, preserve=whitespace(node))
    sizes = [
        max((size(owner) for _, owner in line.runs), default=size(line.node)) for line in found
    ]
    baselines = _baselines(node, found)
    pitches = [LEADING * sizes[0]] + [b - a for a, b in pairwise(baselines)]
    width = max(_advance(line) for line in found)
    left = offset(node, "x") - _SHARE[anchor(node)] * width
    top = baselines[0] - ASCENT * pitches[0]
    m = transform(chain)
    placed = place(m, left, top, width, sum(pitches))
    shape_id = em.take_id()
    made = element("p:sp")
    properties = element("p:nvSpPr", made)
    element("p:cNvPr", properties, id=str(shape_id), name=shape_name(node, shape_id))
    element("p:cNvSpPr", properties, txBox="1")
    element("p:nvPr", properties)
    body = element("p:spPr", made)
    xfrm(placed, body)
    element("a:avLst", element("a:prstGeom", body, prst="rect"))
    element("a:noFill", body)
    words = element("p:txBody", made)
    frame = element(
        "a:bodyPr", words, wrap="none", lIns="0", tIns="0", rIns="0", bIns="0", anchor="t"
    )
    element("a:noAutofit", frame)
    element("a:lstStyle", words)
    align = ALIGN[anchor(node)]
    for line, pitch, own in zip(found, pitches, sizes, strict=True):
        paragraph = element("a:p", words)
        spaced = element("a:lnSpc", element("a:pPr", paragraph, algn=align))
        element("a:spcPts", spaced, val=str(round(pitch * m.scale * HUNDREDTHS)))
        for text, owner in line.runs:
            run(paragraph, chains[id(owner)], owner, text, lang=em.lang, scale=m.scale)
        _end(paragraph, own * m.scale, em.lang)
    em.add(made, placed)


def run(
    paragraph: Any,
    chain: Chain,
    owner: CarrierNode,
    text: str,
    *,
    lang: str,
    scale: float,
) -> None:
    """One `a:r`: its owner's properties and its text."""
    underline, strike = decoration(owner)
    attrs = {"sz": str(round(size(owner) * scale * HUNDREDTHS))}
    if lang:
        attrs["lang"] = lang
    if weight(owner) >= BOLD_FROM:
        attrs["b"] = "1"
    if italic(owner):
        attrs["i"] = "1"
    if underline:
        attrs["u"] = "sng"
    if strike:
        attrs["strike"] = "sngStrike"
    if spacing(owner):
        attrs["spc"] = str(round(spacing(owner) * scale * HUNDREDTHS))
    if baseline(owner):
        attrs["baseline"] = str(baseline(owner))
    made = element("a:r", paragraph)
    properties = element("a:rPr", made, **attrs)
    line = element("a:ln", properties)
    if paint.line(chain, line):
        grown = scale if stroke.scaling(chain) else 1.0
        line.set("w", str(emu(stroke.width(chain) * grown)))
    else:
        properties.remove(line)
    paint.fill(chain, properties)
    face = typeface(owner)
    if face is not None:
        for tag in ("a:latin", "a:ea", "a:cs"):
            element(tag, properties, typeface=face)
    element("a:t", made).text = text


def typeface(node: CarrierNode) -> str | None:
    """The first family the stack names that is not a CSS generic, or `None`."""
    for family in (inherited(node, "font-family") or "").split(","):
        name = family.strip().strip("'\"").strip()
        if name and name.casefold() not in GENERIC:
            return name
    return None


def size(node: CarrierNode) -> float:
    """`font-size`, inherited, in user units."""
    return style(node).size


def weight(node: CarrierNode) -> int:
    """`font-weight`, inherited: `normal` 400, `bold` 700, or its number."""
    return style(node).weight


def italic(node: CarrierNode) -> bool:
    return style(node).italic


def spacing(node: CarrierNode) -> float:
    """`letter-spacing`, inherited, in user units."""
    return style(node).spacing


def anchor(node: CarrierNode) -> str:
    """`text-anchor`, inherited: `start`, `middle` or `end`."""
    stated = (inherited(node, "text-anchor") or "start").strip()
    return stated if stated in ALIGN else "start"


def decoration(node: CarrierNode) -> tuple[bool, bool]:
    """`text-decoration`, from the nearest node that states it: underline, line-through."""
    words = (inherited(node, "text-decoration") or "none").split()
    return ("underline" in words, "line-through" in words)


def baseline(node: CarrierNode) -> int:
    """`baseline-shift`, from the nearest node that states it, as `a:rPr`'s `baseline`."""
    stated = (inherited(node, "baseline-shift") or "").strip()
    return {"super": SUPER, "sub": SUB}.get(stated, 0)


def whitespace(node: CarrierNode) -> bool:
    """`xml:space="preserve"`, inherited."""
    return preserved(node)


def shift(node: CarrierNode) -> float:
    """`dy`, the line's move down; a `dx` is refused, as `pptx.text.lines@1` refuses it."""
    dx = length(node.attr("dx"), 0.0)
    if dx:
        raise TargetError(
            f"<{node.tag.partition('|')[2]}> at {node.at}: dx={node.attr('dx')!r} moves a run, "
            "and a DrawingML run has no offset",
            symbol="OW_TARGET_TEXT_INVALID",
            fix="ow out check --stage final   # pptx.text.lines@1 names the same problem",
        )
    return length(node.attr("dy"), 0.0)


def _baselines(node: CarrierNode, found: list[Line]) -> list[float]:
    """Each line's baseline: its `y`, else the line before's, plus its `dy`."""
    out = [offset(node, "y") + shift(node)]
    for line in found[1:]:
        stated = line.node.attr("y")
        start = offset(line.node, "y") if stated is not None else out[-1]
        here = start + shift(line.node)
        if here <= out[-1]:
            raise TargetError(
                f"<tspan> at {line.node.at}: its baseline is not below the line before's",
                symbol="OW_TARGET_TEXT_INVALID",
                fix="ow out check --stage final   # pptx.text.lines@1 names the same problem",
            )
        out.append(here)
    return out


def _advance(line: Line) -> float:
    """The frame's width for one line (module docstring)."""
    return sum(
        (NOMINAL_ADVANCE * size(owner) + spacing(owner)) * len(text) for text, owner in line.runs
    )


def _end(paragraph: Any, points: float, lang: str) -> None:
    """`a:endParaRPr`: the size and language of the paragraph's end, which an empty line
    takes."""
    attrs = {"sz": str(round(points * HUNDREDTHS))}
    if lang:
        attrs["lang"] = lang
    element("a:endParaRPr", paragraph, **attrs)


def _chains(node: CarrierNode, chain: Chain) -> Iterator[tuple[CarrierNode, Chain]]:
    """Each node of the text with its chain."""
    yield node, chain
    for child in node.children():
        if child.tag == TSPAN:
            yield from _chains(child, (*chain, child))
