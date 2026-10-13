"""`lower.transform`: a node's matrix, its ancestors' then its own. D795.

The arithmetic is `_geometry`'s. A preset shape keeps its box and takes the matrix as an offset,
an extent, a rotation and a flip (`_geometry.place`). A line's two ends and, in later families, a
freeform's points take the matrix directly, which holds any rotation of a scale exactly.
"""

from __future__ import annotations

from omniweave_target_pptx.lower._geometry import Matrix, chain
from omniweave_target_pptx.lower._style import Chain

__all__ = ["transform"]


def transform(nodes: Chain) -> Matrix:
    """The matrix of `nodes`, the slide root first and its own transform left out."""
    return chain(nodes)
