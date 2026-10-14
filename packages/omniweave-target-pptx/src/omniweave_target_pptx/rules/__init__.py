"""owsvg/1's hand-written rules, one rule a file. **D789-D791, D793, D794.**

16-roadmap.md W9.2 asks for "`rules/` at one rule per file with one test per file", and 09
section 12.1 lists the bands they fill. D789 built the structural band (orders 10-19), D790 the
grammar band (40-49) and D791 the references and effects (50-52). The forbidden, conditional,
closed-set, normalize and bake rows are the table's own rules
(`omniweave_core.out.conformance.table_pack()`), the cite facts and the cite batch are
`cite_pack()`'s. D793 adds the line rule (53) and the measurement band (60), and D794 the
document band (90).

## Rulings

1. **Each module holds one rule and exports it as `SPEC`.** `rules()` groups the specs by band,
   so the pack is assembled in one place and a rule is reviewed, tested and versioned alone.
2. **The slide is one `<svg>` root** (`unit_root`). A root of another element, or an `<svg>`
   nested inside the slide, is `OW_TARGET_UNIT_MALFORMED`: one unit is one slide.
   ppt-master admits a nested `<svg>` only as an image crop wrapper
   (`drawingml/elements.py:4856-4892`), and owsvg/1 crops with `clip-path` on `<image>`.
3. **The canvas is the root's `viewBox`** (`canvas`), `OW_TARGET_CANVAS_MISMATCH`:
   - it is `0 0 W H`, positive integers, single spaces;
   - W and H are within PowerPoint's slide bounds, 1 to 56 inches, which at 9525 EMU a user unit
     is 96 to 5376 (ppt-master's `canvas_contract.py:82-126`);
   - the root carries no `transform`, and a `width` or `height` on it is W or H, because either
     would scale the slide away from its canvas;
   - where the check is given a Brief (the final stage), W:H is the Brief's `canvas format`,
     read as `a:b`. A format that is not a ratio cannot be held by a slide and is the same
     finding. `format` is a Brief fact, not a card key (09 section 12.1).
4. **`data-ow-el` is unique in the unit** (`el_unique`), `OW_TARGET_EL_DUPLICATE` (OUT21).
   Presence is `ow out stamp`'s, which addresses every element with text or a cite (D767).
5. **D790: a value a `normalize` row settles is that row's warning, not a grammar error.** Each
   grammar rule reads an attribute's value as the table's normalize rows leave it
   (`RuleCtx.constructs`), so `fill="#abc"` is `OW-T-210`'s warning alone, and `fill="#abcd"`,
   which no row settles, is this band's error. A `style` declaration has no normalize row
   (D781 ruling 5) and is read as written, except that a style length may carry `px`, as CSS
   writes one.
6. **D790: the grammar band is ten rules, each one family's values**, each grounded in
   ppt-master's exporter: paint (40), opacity (41), lengths (42), point lists (43), path data
   (44), transforms (45), keywords (46), strokes (47), fonts (48) and gradients (49). A rule
   names the value, where it is written, and the spelling that would hold.
7. **D790: a value is refused where it means nothing.** `points` stands on a polygon or
   polyline, `d` on a path, `text-anchor` on a `<text>`, `baseline-shift` on a `<tspan>`, and
   `xml:space` on text. DrawingML has nowhere to put the others, and a value the compiler would
   drop is a value the author believes is honoured.
8. **D791: every local reference resolves to what it needs** (`reference`, 50). An id is
   defined once in the slide. A `fill` names a gradient or a pattern, a `stroke` a gradient,
   `filter`, `marker-start`, `marker-end` and `clip-path` a `<filter>`, `<marker>` and
   `<clipPath>`, and a `<use>` a local shape, group, text, image or symbol. An `<image>` names
   its picture as `asset-slot:<sha256>`, and an `<a>` links to `#u<NN>` or an `https:` page.
   Resolution is in the slide: a unit is one `<svg>`, and an id in another slide is another
   document's.
9. **D791: one effect of each kind DrawingML has** (`effect`, 51). A filter holds one drop
   shadow or one blur, a marker one shape, a clip one shape. A line end stands on a `<line>` or
   `<path>`, a clip on an `<image>`, and an image takes a filter or a clip, not both.
10. **D791: a definition stands in `<defs>` with an id, and a pattern names a DrawingML preset**
    (`definitions`, 52). ppt-master falls back to `ltUpDiag` for a pattern with no preset;
    owsvg/1 refuses, because a fallback draws a pattern the author did not choose.
11. **D793: a positioned line is a paragraph of its own text box** (`text_lines`, 53). It is a
    direct child of its `<text>`, at the text's `x`: DrawingML's paragraphs share their box's
    position, and no paragraph begins inside a run.
12. **D793: a text's measured lines stay on the slide** (`text_canvas`, 60,
    `needs={"measure"}`). Its model is ppt-master's, stated in every message: single-line width
    per positioned line, vertical wrapping not modeled. A rotated or scaled text is outside the
    model, and a text with no face is the framework's recorded skip.
13. **D794: an undeclared type size may stay a one-off, never a pattern** (`type_budget`, 90,
    a document rule at the final stage). A size within 2 of a Brief typography anchor is
    declared. Any other is counted across the deck by the framework, and its second occurrence
    is a warning and its third an error (`limits["undeclared_size_max"]`, 2). A Brief that names
    no size sets no budget.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import TYPE_CHECKING

from omniweave_target_pptx.rules import (
    canvas,
    definitions,
    effect,
    el_unique,
    enums,
    font,
    gradient,
    length,
    opacity,
    paint,
    path_data,
    points,
    reference,
    stroke,
    text_canvas,
    text_lines,
    transform,
    type_budget,
    unit_root,
)

if TYPE_CHECKING:
    from omniweave_core.out import RuleSpec

__all__ = ["rules"]


def rules() -> Mapping[str, Sequence[RuleSpec]]:
    """Ruling 1: the hand-written half of the pack; the driver adds `table_pack()`'s half."""
    return {
        "structure": (unit_root.SPEC, canvas.SPEC, el_unique.SPEC),
        "grammar": (
            paint.SPEC,
            opacity.SPEC,
            length.SPEC,
            points.SPEC,
            path_data.SPEC,
            transform.SPEC,
            enums.SPEC,
            stroke.SPEC,
            font.SPEC,
            gradient.SPEC,
        ),
        "reference": (reference.SPEC, effect.SPEC, definitions.SPEC, text_lines.SPEC),
        "measurement": (text_canvas.SPEC,),
        "document": (type_budget.SPEC,),
    }
