"""`derive.merge.llm`: the resolution funnel's `[75, 92)` band, decided by a model. D726.

06 section 5.1's stage [8], over `omniweave_llm.merge`'s view and answer. 06:842 places it at
rank 2, phase 30, `corpus` granularity: a batch's pairs come from entities across the corpus.
D731 lifted its call into `omniweave_llm.decision_pass.DecisionPass`, which the report lane
shares, with D726's rulings 7-9 as that module's 1-3.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, ClassVar, Final

from omniweave_llm import merge
from omniweave_llm.decision_pass import DecisionPass

if TYPE_CHECKING:
    from collections.abc import Mapping

    from omniweave_llm.merge import PairsView

__all__ = ["DRIVER_ID", "MergeLLM"]

DRIVER_ID: Final = "derive.merge.llm"


class MergeLLM(DecisionPass):
    """The billed `merge` lane: entity pairs in the ambiguous band, decided by position."""

    DRIVER_ID: ClassVar[str] = DRIVER_ID
    LANE: ClassVar[str] = merge.LANE
    HEAD: ClassVar[bytes] = b'"t":"batch"'

    def _read(self, raw: bytes) -> PairsView:
        return merge.read_pairs(raw)

    def _frames(self, view: Any, answer: Mapping[str, Any]) -> list[dict[str, Any]]:
        return merge.answer_frames(view, answer)

    def _unparsed(self, view: Any, raw: str, problems: list[str]) -> list[dict[str, Any]]:
        return merge.unparsed_frames(view, raw, problems)
