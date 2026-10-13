"""The lowering walk: owsvg/1 elements to DrawingML shapes, dispatched by the table. D795.

09 section 5.2: an element is lowered by the function its native row's `maps_to` names, resolved
from the table (`omniweave_core.out.lowering`), so a construct the table gains without a function
is preflight check 1's refusal and never a silent skip. The `Emitter` holds what the functions
share: the tree shapes go into (the slide's shape tree, or a group), the next shape id, and each
open group's child boxes, from which the group's own box is made.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass, field
from types import ModuleType
from typing import TYPE_CHECKING, Any, Final

from omniweave_core.errors import TargetError
from omniweave_core.out.lowering import Row, refuse_unmapped, resolve

from omniweave_target_pptx.lower import paint, stroke
from omniweave_target_pptx.lower._geometry import Matrix, Placed, emu
from omniweave_target_pptx.lower._style import element
from omniweave_target_pptx.lower.ids import shape_name

if TYPE_CHECKING:
    from omniweave_core.out.carrier import CarrierNode, Selector

    from omniweave_target_pptx.lower._style import Chain

__all__ = ["Emitter", "Handler"]

Handler = Callable[["Emitter", "CarrierNode", "Chain"], None]
FIRST_ID: Final = 2
"""02-architecture.md's compile walkthrough: "shape ids from a per-unit counter seeded at 2"."""


@dataclass
class Emitter:
    """One slide's walk: where shapes go, the next id, and each open group's child boxes."""

    rows: Sequence[Row]
    families: Mapping[str, ModuleType]
    ignored: Sequence[Selector]
    tree: Any
    lang: str = ""
    """The Brief's primary language, each run's `lang` (D797)."""
    next_id: int = FIRST_ID
    boxes: list[list[Placed]] = field(default_factory=lambda: [[]])
    handlers: dict[str, Handler] = field(default_factory=dict)

    def handler(self, node: CarrierNode) -> Handler:
        """The function the first native element row matching `node` names."""
        for row in self.rows:
            if row.selector.kind == "element" and row.selector.matches(node):
                maps_to = row.construct.maps_to or ""
                if maps_to not in self.handlers:
                    found = resolve(maps_to, self.families)
                    if found is None:
                        refuse_unmapped([row.construct], "pptx")
                    self.handlers[maps_to] = found  # type: ignore[assignment]
                return self.handlers[maps_to]
        raise TargetError(
            f"<{node.tag.partition('|')[2]}> at {node.at} matches no native row of owsvg/1",
            symbol="OW_TARGET_CONSTRUCT_UNMAPPED",
            fix="ow out check --stage final   # the gate refuses what no row declares",
        )

    def children(self, node: CarrierNode, chain: Chain) -> None:
        """Lower each child of `node` in document order, skipping what the table ignores."""
        for child in node.children():
            if any(s.matches(child) for s in self.ignored):
                continue
            self.handler(child)(self, child, (*chain, child))

    def take_id(self) -> int:
        taken = self.next_id
        self.next_id += 1
        return taken

    def add(self, made: Any, placed: Placed) -> None:
        """`made` into the current tree, its box into the open group's."""
        self.tree.append(made)
        self.boxes[-1].append(placed)

    @contextmanager
    def group(self, made: Any) -> Iterator[list[Placed]]:
        """Shapes made inside go into `made`; the boxes they took are yielded to its maker."""
        outer = self.tree
        self.tree = made
        self.boxes.append([])
        try:
            yield self.boxes[-1]
        finally:
            self.tree = outer
            self.boxes.pop()

    def shape(
        self,
        node: CarrierNode,
        chain: Chain,
        placed: Placed,
        m: Matrix,
        geometry: Callable[[Any], None],
        *,
        filled: bool = True,
    ) -> None:
        """One `p:sp`: its name, box, geometry, fill and line, as DrawingML orders them."""
        shape_id = self.take_id()
        made = element("p:sp")
        properties = element("p:nvSpPr", made)
        element("p:cNvPr", properties, id=str(shape_id), name=shape_name(node, shape_id))
        element("p:cNvSpPr", properties)
        element("p:nvPr", properties)
        body = element("p:spPr", made)
        xfrm(placed, body)
        geometry(body)
        if filled:
            paint.fill(chain, body)
        else:
            element("a:noFill", body)
        line = element("a:ln", body, cap=stroke.cap(chain))
        drawn = paint.line(chain, line)
        grown = m.scale if stroke.scaling(chain) else 1.0
        line.set("w", str(emu(stroke.width(chain) * grown) if drawn else 0))
        stroke.dash(chain, line)
        stroke.join(chain, line)
        self.add(made, placed)


def xfrm(placed: Placed, parent: Any, *, child: Placed | None = None) -> Any:
    """`a:xfrm` for a box: its rotation and flips, offset and extent, and a group's child frame."""
    attrs: dict[str, str] = {}
    if placed.rot:
        attrs["rot"] = str(placed.rot)
    if placed.flip_h:
        attrs["flipH"] = "1"
    if placed.flip_v:
        attrs["flipV"] = "1"
    made = element("a:xfrm", parent, **attrs)
    element("a:off", made, x=str(placed.x), y=str(placed.y))
    element("a:ext", made, cx=str(placed.cx), cy=str(placed.cy))
    if child is not None:
        element("a:chOff", made, x=str(child.x), y=str(child.y))
        element("a:chExt", made, cx=str(child.cx), cy=str(child.cy))
    return made
