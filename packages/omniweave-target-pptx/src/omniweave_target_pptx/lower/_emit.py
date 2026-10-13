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
from pptx.oxml.ns import qn

from omniweave_target_pptx.lower import effects, paint, stroke
from omniweave_target_pptx.lower._geometry import Matrix, Placed, angle, emu
from omniweave_target_pptx.lower._style import element, inherited
from omniweave_target_pptx.lower.ids import shape_name

if TYPE_CHECKING:
    from omniweave_core.out.carrier import CarrierNode, Selector

    from omniweave_target_pptx.lower._style import Chain

__all__ = ["Asset", "Emitter", "Handler"]

Handler = Callable[["Emitter", "CarrierNode", "Chain"], None]
FIRST_ID: Final = 2
"""02-architecture.md's compile walkthrough: "shape ids from a per-unit counter seeded at 2"."""


@dataclass(frozen=True, slots=True)
class Asset:
    """A frozen picture: its bytes and its size in pixels (preflight check 2, D800)."""

    blob: bytes
    width: int
    height: int


def _unembedded(blob: bytes) -> str:
    """No slide to embed in: an `Emitter` built outside `_pack.build()` holds no picture."""
    del blob
    return ""


def _unlinked(href: str) -> tuple[str, str]:
    """No slide to link from: an `Emitter` built outside `_pack.build()` holds no link."""
    del href
    return ("", "")


@dataclass
class Emitter:
    """One slide's walk: where shapes go, the next id, and each open group's child boxes."""

    rows: Sequence[Row]
    families: Mapping[str, ModuleType]
    ignored: Sequence[Selector]
    tree: Any
    lang: str = ""
    """The Brief's primary language, each run's `lang` (D797)."""
    definitions: Mapping[str, CarrierNode] = field(default_factory=dict)
    """The slide's elements by `id`: what a `url(#id)` paint names (D798)."""
    assets: Mapping[str, Asset] = field(default_factory=dict)
    """Each picture's frozen asset by its slot (D800)."""
    embed: Callable[[bytes], str] = _unembedded
    """A picture's bytes as an image part of the slide: its relationship's id (D800)."""
    linker: Callable[[str], tuple[str, str]] = _unlinked
    """A link's `href` as the slide's relationship id and its action, `""` for a page (D801)."""
    linked: str | None = None
    """The `href` of the `<a>` the walk is inside, if any (D801)."""
    using: tuple[str, ...] = ()
    """The ids each open `<use>` clones, innermost last: a `<use>` may not reach itself."""
    cloning: int = 0
    """How many `<use>`s deep the walk is: a clone's shapes take no address (D801)."""
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

    def name(self, node: CarrierNode, shape_id: int) -> str:
        """A shape's `p:cNvPr` name: its address (`lower.ids`), or its kind and id inside a
        clone, which shares its original's address and may not repeat it."""
        if self.cloning:
            return f"{node.tag.partition('|')[2]} {shape_id}"
        return shape_name(node, shape_id)

    def click(self, named: Any) -> None:
        """`a:hlinkClick` on a shape's `p:cNvPr` while the walk is inside an `<a>`."""
        if self.linked is None:
            return
        rid, action = self.linker(self.linked)
        made = element("a:hlinkClick", named)
        made.set(qn("r:id"), rid)
        if action:
            made.set("action", action)

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
        named = element("p:cNvPr", properties, id=str(shape_id), name=self.name(node, shape_id))
        self.click(named)
        element("p:cNvSpPr", properties)
        element("p:nvPr", properties)
        body = element("p:spPr", made)
        xfrm(placed, body)
        geometry(body)
        turn = 0.0 if placed.rot else angle(m)  # a freeform's or a line's points carry it
        if filled:
            paint.fill(chain, body, definitions=self.definitions, turn=turn)
        else:
            element("a:noFill", body)
        line = element("a:ln", body, cap=stroke.cap(chain))
        drawn = paint.line(chain, line, definitions=self.definitions, turn=turn)
        grown = m.scale if stroke.scaling(chain) else 1.0
        line.set("w", str(emu(stroke.width(chain) * grown) if drawn else 0))
        stroke.dash(chain, line)
        stroke.join(chain, line)
        ends = (
            (effects.head(chain, self.definitions), "a:headEnd"),
            (effects.tail(chain, self.definitions), "a:tailEnd"),
        )
        for marker, tag in ends:
            if marker is not None:
                effects.line_end(marker, line, tag, width=stroke.width(chain))
        found = effects.apply(node, self.definitions)
        if found is not None:
            fill = inherited(chain, "fill")
            effects.effect(found, body, scale=m.scale, turn=turn, fill=fill)
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
