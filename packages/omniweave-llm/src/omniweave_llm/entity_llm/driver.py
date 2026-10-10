"""`derive.entity.llm`: one billed prompt per Segment, and one glean when the model says so. D711.

The Pass is `omniweave_llm.lane_pass.LanePass`, whose docstring carries D711's rulings (moved there
by D722, unchanged). This module is the `entity` lane's: its id, its lists, and D710's translation.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, ClassVar, Final

from omniweave_llm import entity
from omniweave_llm.lane_pass import CHAT_PATH, GLEAN, MAX_ATTEMPTS, LanePass

if TYPE_CHECKING:
    from collections.abc import Mapping

    from omniweave_llm.view import SegmentView

__all__ = ["CHAT_PATH", "DRIVER_ID", "GLEAN", "MAX_ATTEMPTS", "EntityLLM"]

DRIVER_ID: Final = "derive.entity.llm"


class EntityLLM(LanePass):
    """The billed `entity` lane: entities and relations, grounded by quote, through a model."""

    DRIVER_ID: ClassVar[str] = DRIVER_ID
    LANE: ClassVar[str] = entity.LANE
    LISTS: ClassVar[tuple[str, ...]] = ("entities", "relations")

    def _frames(self, view: SegmentView, answer: Mapping[str, Any]) -> list[dict[str, Any]]:
        return entity.answer_frames(view, answer)

    def _unparsed(self, view: SegmentView, raw: str, problems: list[str]) -> list[dict[str, Any]]:
        return entity.unparsed_frames(view, raw, problems)
