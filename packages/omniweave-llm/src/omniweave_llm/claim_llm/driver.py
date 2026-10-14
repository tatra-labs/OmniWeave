"""`derive.claim.llm`: one billed prompt per Segment, and one glean when the model says so. D722.

The Pass is `omniweave_llm.lane_pass.LanePass` (D711's rulings), over the `claim` lane's prompt and
schema (D708) and D721's translation. A claim's subject binds to the entity its key already names,
so the Pass is placed after the entity lane: rank 2, phase 20 (06:841).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, ClassVar, Final

from omniweave_llm import claim
from omniweave_llm.lane_pass import LanePass

if TYPE_CHECKING:
    from collections.abc import Mapping

    from omniweave_llm.view import SegmentView

__all__ = ["DRIVER_ID", "ClaimLLM"]

DRIVER_ID: Final = "derive.claim.llm"


class ClaimLLM(LanePass):
    """The billed `claim` lane: claims about the corpus's entities, grounded by quote."""

    DRIVER_ID: ClassVar[str] = DRIVER_ID
    LANE: ClassVar[str] = claim.LANE
    LISTS: ClassVar[tuple[str, ...]] = ("claims",)

    def _frames(self, view: SegmentView, answer: Mapping[str, Any]) -> list[dict[str, Any]]:
        return claim.answer_frames(view, answer)

    def _unparsed(self, view: SegmentView, raw: str, problems: list[str]) -> list[dict[str, Any]]:
        return claim.unparsed_frames(view, raw, problems)
