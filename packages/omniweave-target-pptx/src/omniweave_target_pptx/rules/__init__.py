"""owsvg/1's hand-written rules, one rule a file. **D789, D790.**

16-roadmap.md W9.2 asks for "`rules/` at one rule per file with one test per file", and 09
section 12.1 lists the bands they fill. D789 built the structural band (orders 10-19) and D790
the grammar band (40-49). The forbidden, conditional, closed-set, normalize and bake rows are
the table's own rules (`omniweave_core.out.conformance.table_pack()`), and the measurement and
reference bands are later cells.

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
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import TYPE_CHECKING

from omniweave_target_pptx.rules import (
    canvas,
    el_unique,
    enums,
    font,
    gradient,
    length,
    opacity,
    paint,
    path_data,
    points,
    stroke,
    transform,
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
    }
