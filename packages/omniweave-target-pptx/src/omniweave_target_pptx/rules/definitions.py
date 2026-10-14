"""`pptx.defs@1`: a definition stands in `<defs>` with an id, and a pattern names its preset.
D791.

ppt-master: each definition is a direct child of `<defs>` with a unique, non-empty id
(`drawingml/utils.py:229-236`, `:1829-1863`), and a pattern is a DrawingML preset named by
`data-pptx-pattern`, falling back to `ltUpDiag` with a warning when none is named
(`styles.py:211`; `checker.py:5310-5374`). owsvg/1 names the preset with `data-ow-preset` and has
no fallback: a pattern with no preset, or another name, is refused, because a fallback draws a
pattern the author did not choose. A gradient's placement is `pptx.gradient@1`'s. Each finding
carries the code of the row the definition is written under.
"""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from typing import TYPE_CHECKING, Final

from omniweave_core.out import RuleSpec

from omniweave_target_pptx.rules._common import finding, lineage, local

if TYPE_CHECKING:
    from omniweave_core.out import Finding, RuleCtx
    from omniweave_core.out.carrier import CarrierNode

__all__ = ["DEFINITIONS", "PRESETS", "SPEC", "definitions"]

RULE: Final = "pptx.defs@1"
DEFINITIONS: Final[Mapping[str, str]] = {
    "svg|filter": "effect.filter-def",
    "svg|marker": "effect.marker-def",
    "svg|clipPath": "effect.clip-def",
    "svg|pattern": "def.pattern",
    "svg|symbol": "def.symbol",
}
"""Each definition's tag to the row it is written under."""
PRESETS: Final = frozenset(
    {
        *(f"pct{n}" for n in (5, 10, 20, 25, 30, 40, 50, 60, 70, 75, 80, 90)),
        "horz", "vert", "ltHorz", "ltVert", "dkHorz", "dkVert", "narHorz", "narVert",
        "dashHorz", "dashVert", "cross", "dnDiag", "upDiag", "ltDnDiag", "ltUpDiag", "dkDnDiag",
        "dkUpDiag", "wdDnDiag", "wdUpDiag", "dashDnDiag", "dashUpDiag", "diagCross", "smCheck",
        "lgCheck", "smGrid", "lgGrid", "dotGrid", "smConfetti", "lgConfetti", "horzBrick",
        "diagBrick", "solidDmnd", "openDmnd", "dotDmnd", "plaid", "sphere", "weave", "divot",
        "shingle", "wave", "trellis", "zigZag",
    }
)  # fmt: skip
"""DrawingML's `ST_PresetPatternVal`, all 54."""


def definitions(ctx: RuleCtx) -> Iterator[Finding]:
    """Each definition in `<defs>` with an id; each pattern a DrawingML preset."""
    if ctx.doc is None or ctx.unit is None:
        return
    for n, above in lineage(ctx.doc.root()):
        construct = DEFINITIONS.get(n.tag)
        if construct is None:
            continue
        if above[-1] != "svg|defs":
            yield _said(ctx, n, construct, f"a <{local(n.tag)}> is a definition: put it in <defs>")
        if not (n.attr("id") or "").strip():
            yield _said(ctx, n, construct, f"a <{local(n.tag)}> has an id for its users to name")
        if n.tag == "svg|pattern":
            preset = n.attr("data-ow-preset")
            if preset not in PRESETS:
                yield _said(
                    ctx, n, "def.preset",
                    f"data-ow-preset={preset!r} is no DrawingML preset pattern",
                )  # fmt: skip


def _said(ctx: RuleCtx, n: CarrierNode, construct: str, msg: str) -> Finding:
    code = ctx.constructs.row(construct).code
    return finding(ctx, n, rule=RULE, code=code, construct=construct, msg=msg)


SPEC: Final = RuleSpec(
    RULE,
    52,
    "unit",
    frozenset(
        {"OW_TARGET_EFFECT_INVALID", "OW_TARGET_FILL_INVALID", "OW_TARGET_REFERENCE_UNRESOLVED"}
    ),
    definitions,
)
