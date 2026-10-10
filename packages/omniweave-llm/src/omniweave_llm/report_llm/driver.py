"""`derive.report.llm`: a community report on first descent, one community a prompt. D731.

06 sections 6.2-6.3. The Pass is `omniweave_llm.decision_pass.DecisionPass` (D726's rulings, lifted
by D731) over the report lane's view and answer. 06:843 places it at rank 2, phase 40, `corpus`
granularity: a community's members come from documents across the corpus.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, ClassVar, Final

from omniweave_llm import report
from omniweave_llm.decision_pass import DecisionPass

if TYPE_CHECKING:
    from collections.abc import Mapping

    from omniweave_llm.report import CommunityView

__all__ = ["DRIVER_ID", "ReportLLM"]

DRIVER_ID: Final = "derive.report.llm"


class ReportLLM(DecisionPass):
    """The billed `report` lane: one community's report, from the context the host assembled."""

    DRIVER_ID: ClassVar[str] = DRIVER_ID
    LANE: ClassVar[str] = report.LANE
    HEAD: ClassVar[bytes] = b'"t":"community"'

    def _read(self, raw: bytes) -> CommunityView:
        return report.read_community(raw)

    def _frames(self, view: Any, answer: Mapping[str, Any]) -> list[dict[str, Any]]:
        return report.answer_frames(view, answer)

    def _unparsed(self, view: Any, raw: str, problems: list[str]) -> list[dict[str, Any]]:
        return report.unparsed_frames(view, raw, problems)
