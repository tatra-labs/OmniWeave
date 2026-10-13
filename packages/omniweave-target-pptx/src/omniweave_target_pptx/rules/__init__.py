"""owsvg/1's hand-written rules, one rule a file. **D789.**

16-roadmap.md W9.2 asks for "`rules/` at one rule per file with one test per file", and 09
section 12.1 lists the bands they fill. This cell builds the structural band (orders 10-19).
The forbidden, conditional, closed-set, normalize and bake rows are the table's own rules
(`omniweave_core.out.conformance.table_pack()`), and the grammar and measurement bands are
later cells.

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
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import TYPE_CHECKING

from omniweave_target_pptx.rules import canvas, el_unique, unit_root

if TYPE_CHECKING:
    from omniweave_core.out import RuleSpec

__all__ = ["rules"]


def rules() -> Mapping[str, Sequence[RuleSpec]]:
    """Ruling 1: the hand-written half of the pack; the driver adds `table_pack()`'s half."""
    return {"structure": (unit_root.SPEC, canvas.SPEC, el_unique.SPEC)}
