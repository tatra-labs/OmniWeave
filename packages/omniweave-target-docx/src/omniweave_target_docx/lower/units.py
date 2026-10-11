"""`ow.unit`: one `<section>` a unit, lowered between continuous section breaks."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from omniweave_core.out.carrier import CarrierNode

    from omniweave_target_docx.lower._emit import Emitter

__all__ = ["section"]


def section(em: Emitter, node: CarrierNode) -> None:
    """The unit's content. Its section break is the build's, before the unit is dispatched."""
    em.flow(node)
