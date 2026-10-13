"""`lower.defs`: definitions draw nothing where they stand; their users read them. D795.

`<defs>` holds gradients, patterns, filters, markers, clips and symbols, each drawn only where a
`url(#id)` or an `href` names it. This family's two functions are the walk's: `definitions`
lowers a `<defs>` to nothing, and `definition_id` reads the `id` a reference resolves by. `use`,
`symbol` and `reference` are later families.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from omniweave_core.out.carrier import CarrierNode

    from omniweave_target_pptx.lower._style import Chain

__all__ = ["definition_id", "definitions"]


def definitions(em: Any, node: CarrierNode, chain: Chain) -> None:
    """A `<defs>` draws nothing where it stands."""
    del em, node, chain


def definition_id(node: CarrierNode) -> str | None:
    """The `id` a `url(#id)` or `href="#id"` names this node by."""
    return node.attr("id")
