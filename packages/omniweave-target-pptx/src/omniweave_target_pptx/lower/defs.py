"""`lower.defs`: definitions draw nothing where they stand; their users read them. D795.

`<defs>` holds gradients, patterns, filters, markers, clips and symbols, each drawn only where a
`url(#id)` or an `href` names it. This family's two functions are the walk's: `definitions`
lowers a `<defs>` to nothing, and `definition_id` reads the `id` a reference resolves by. D800
adds `reference`, an `href` as written: a picture's `asset-slot:` (`lower.media`).

D801: **a `<use>` is a group named by its own address, holding a clone of what its `href`
names**: a shape, a group, a text, a picture or a `<symbol>`, whose clone is its content. SVG
clones the target as the `<use>`'s child, so the clone inherits from the `<use>`, and the
`<use>`'s `x` and `y`, and a symbol's `viewBox` fitted into the `<use>`'s box, are the matrix's
(`_geometry.chain`). A clone's shapes take no address, since the address is its original's and
may not repeat (`Emitter.name`). A `<use>` that reaches itself through the uses it clones is
refused, as an id naming nothing is (`OW_TARGET_REFERENCE_UNRESOLVED`).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from omniweave_core.errors import TargetError

from omniweave_target_pptx.lower._style import named
from omniweave_target_pptx.lower.group import framed
from omniweave_target_pptx.rules.reference import USE_TARGETS

if TYPE_CHECKING:
    from omniweave_core.out.carrier import CarrierNode

    from omniweave_target_pptx.lower._emit import Emitter
    from omniweave_target_pptx.lower._style import Chain

__all__ = ["definition_id", "definitions", "reference", "symbol", "use"]


def definitions(em: Any, node: CarrierNode, chain: Chain) -> None:
    """A `<defs>` draws nothing where it stands."""
    del em, node, chain


def use(em: Emitter, node: CarrierNode, chain: Chain) -> None:
    """A `<use>` as a group holding a clone of what it names (module docstring)."""
    href = reference(node)
    target = named(
        href, em.definitions, USE_TARGETS, what="a shape, group, text, picture or symbol"
    )
    key = target.attr("id") or ""
    if key in em.using:
        raise TargetError(
            f"<use> at {node.at}: {href} reaches itself through the uses it clones",
            symbol="OW_TARGET_REFERENCE_UNRESOLVED",
            fix="ow out check --stage final",
        )

    def draw() -> None:
        em.using = (*em.using, key)
        em.cloning += 1
        try:  # a <symbol> is the table's `lower.defs:symbol`: its content
            em.handler(target)(em, target, (*chain, target))
        finally:
            em.using = em.using[:-1]
            em.cloning -= 1

    framed(em, node, chain, draw)


def symbol(em: Emitter, node: CarrierNode, chain: Chain) -> None:
    """A `<symbol>`'s content, lowered where a `<use>` clones it."""
    em.children(node, chain)


def reference(node: CarrierNode) -> str:
    """`href` as written: a picture's `asset-slot:`, or `#id` for a `<use>`."""
    return node.attr("href") or ""


def definition_id(node: CarrierNode) -> str | None:
    """The `id` a `url(#id)` or `href="#id"` names this node by."""
    return node.attr("id")
