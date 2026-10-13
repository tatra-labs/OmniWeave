"""One compile: preflight, a slide a unit, then a package whose parts are a function of the IL,
the Brief and the job's clock alone (09 sections 5.1, 6 and 12.1). D795.

python-pptx builds the presentation from its own template, and this module decides what reaches
the package. The template's thumbnail and printer settings are dropped by dropping their
relationships. `dcterms` are the job's clock, `cp:revision` is 1, and the app properties are
fixed. The slide size loses the template's `type="screen4x3"`, which names a 4:3 size the deck
need not have: an absent `type` is `custom`. Every attribute map is sorted, and `write_opc()`
decides the member order and every ZIP field. Each slide uses the template's `Blank` layout,
which python-pptx clones no placeholder from.

The package is checked where it is built. `check_package()` raises on a dangling relationship or
an untyped part before `lower()` returns, so the receipt's `internal_relationships` row is
`enforced-at-build` (09 section 12.1), the claim `test_a_dangling_relationship_is_refused_at_build`
proves by breaking the part graph.

python-pptx exposes no public handle on a slide's shape tree, so `_tree()` reads
`slide.shapes._spTree`, the `p:spTree` element its own shape methods append to (09 section 12.1's
disclosure of private attribute access: an upgrade checks this one).
"""

from __future__ import annotations

import datetime as dt
import io
import zipfile
from collections.abc import Callable, Mapping, Sequence
from types import MappingProxyType
from typing import TYPE_CHECKING, Any, Final

from lxml import etree  # type: ignore[attr-defined] -- lxml ships no stubs
from omniweave_core.errors import TargetError
from omniweave_core.out import provenance as channel
from omniweave_core.out.carrier import parse_selector
from omniweave_core.out.lowering import (
    refuse_normalizable,
    refuse_unmapped,
    rows_of,
    unmapped,
    walk,
)
from omniweave_core.out.opc import check_package, write_opc
from pptx import Presentation
from pptx.opc.constants import RELATIONSHIP_TYPE
from pptx.oxml.ns import qn
from pptx.parts.image import Image
from pptx.util import Emu

from omniweave_target_pptx.lower import (
    cites,
    defs,
    effects,
    geometry,
    gradients,
    group,
    ids,
    links,
    manual,
    media,
    paint,
    paths,
    patterns,
    shapes,
    slide,
    stroke,
    text,
    transform,
)
from omniweave_target_pptx.lower._emit import Asset, Emitter
from omniweave_target_pptx.lower._geometry import emu

if TYPE_CHECKING:
    from omniweave_core.out import AssetLedger, CarrierDoc, ConstructTable, ILBundle, Plan
    from omniweave_core.out.carrier import CarrierNode

__all__ = ["FAMILIES", "build"]

FAMILIES: Final = MappingProxyType(
    {
        f"lower.{module.__name__.rpartition('.')[2]}": module
        for module in (
            cites,
            defs,
            effects,
            geometry,
            gradients,
            group,
            ids,
            links,
            manual,
            media,
            paint,
            paths,
            patterns,
            shapes,
            slide,
            stroke,
            text,
            transform,
        )
    }
)
"""The modules a `maps_to` may name, imported here and never by name (INV-4)."""
_DROPPED: Final = frozenset({RELATIONSHIP_TYPE.THUMBNAIL, RELATIONSHIP_TYPE.PRINTER_SETTINGS})
_BLANK: Final = "Blank"
_APP: Final = (("Application", "omniweave-target-pptx"), ("DocSecurity", "0"))
_PRESENTATION: Final = "ppt/presentation.xml"
_SLIDE_SIZE: Final = qn("p:sldSz")
_PARSER: Final = etree.XMLParser(resolve_entities=False, no_network=True, remove_comments=False)


def build(
    plan: Plan,
    il: ILBundle,
    ledger: AssetLedger,
    *,
    carrier: Callable[[str, str], CarrierDoc],
    table: ConstructTable,
    normalizers: Mapping[str, Callable[[str], str]],
    clock_ns: int,
    max_units: int,
    provenance: str,
) -> bytes:
    """Preflight, then a slide for every unit in Plan order, then the package's bytes."""
    _rosters(plan, il, max_units)
    roots = [carrier(u.il_path, il.text(u.il_path)).root() for u in plan.units]
    rows = rows_of(table)
    refuse_unmapped(unmapped(roots, rows, FAMILIES), "pptx")
    refuse_normalizable(roots, table, normalizers)
    assets = _assets(roots, ledger)
    cited = channel.cited(roots, plan)
    addresses = channel.addresses(roots, rows)
    width, height = _size(roots)
    deck = Presentation()
    _drop(deck)
    deck.slide_width, deck.slide_height = Emu(emu(width)), Emu(emu(height))
    blank = next(layout for layout in deck.slide_layouts if layout.name == _BLANK)
    ignored = tuple(parse_selector(s, table.carrier) for s in table.ignore)
    lang = plan.brief.value("communication", "primary_language") or ""
    slides = [deck.slides.add_slide(blank) for _ in roots]  # first, so a link can jump to any
    by_unit = dict(zip((u.id for u in plan.units), slides, strict=True))
    for root, made in zip(roots, slides, strict=True):
        defined = {n.attr("id") or "": n for n in walk(root) if n.attr("id")}
        em = Emitter(
            rows,
            FAMILIES,
            ignored,
            _tree(made),
            lang,
            defined,
            assets,
            _embedder(made),
            _linker(made, by_unit),
        )
        em.handler(root)(em, root, (root,))
    cites.provenance_part(
        deck,
        cited,
        addresses=addresses,
        name=provenance,
        corpus=plan.corpus,
        slug=plan.slug,
        artifact_gen=plan.artifact_gen,
    )
    _core(deck, plan.slug, clock_ns)
    return _package(deck)


# -- preflight (09 section 5.1) ------------------------------------------------------------------


def _rosters(plan: Plan, il: ILBundle, max_units: int) -> None:
    """Checks 3 and 4: the Plan's roster is the bundle's, and within the card's `max_units`."""
    planned, bundled = [u.id for u in plan.units], [u.id for u in il.units]
    if planned != bundled:
        raise TargetError(
            f"the Plan's units {planned} are not the bundle's {bundled}",
            symbol="OW_TARGET_ROSTER_MISMATCH",
            fix="ow out check --stage final",
        )
    if len(planned) > max_units:
        raise TargetError(
            f"{len(planned)} units, and the card's [compile] max_units is {max_units}",
            symbol="OW_TARGET_TOO_MANY_UNITS",
            fix="ow out targets   # the card's limit",
        )


def _size(roots: Sequence[CarrierNode]) -> tuple[int, int]:
    """One slide size a deck: every unit's `viewBox` must be the first's."""
    sizes = [slide.size(root) for root in roots]
    first = sizes[0] if sizes else None
    if first is None or any(s != first for s in sizes):
        named = ", ".join("none" if s is None else f"{s[0]}x{s[1]}" for s in sizes)
        raise TargetError(
            f"a deck has one slide size, and its units' viewBoxes are {named}",
            symbol="OW_TARGET_CANVAS_MISMATCH",
            fix="ow out check --stage final   # pptx.canvas@1 holds each to the Brief's format",
        )
    return first


def _assets(roots: Sequence[CarrierNode], ledger: AssetLedger) -> dict[str, Asset]:
    """Check 2: every picture's slot is frozen, and its bytes are a picture PowerPoint holds."""
    out: dict[str, Asset] = {}
    for root in roots:
        for node in walk(root):
            slot = node.attr("href") if node.tag == "svg|image" else None
            if slot is None or slot in out:
                continue
            with ledger.open(slot) as stream:
                blob = stream.read()
            try:
                image = Image.from_blob(blob)
                width, height = image.size
                image.ext  # noqa: B018 -- python-pptx refuses a format PowerPoint does not hold
            except (OSError, ValueError):
                raise TargetError(
                    f"{slot} at {node.at} is not a picture PowerPoint holds: PNG, JPEG, GIF, BMP, "
                    "TIFF or WMF",
                    symbol="OW_TARGET_ASSET_FORMAT",
                    fix="ow out assets --slot " + slot,
                ) from None
            out[slot] = Asset(blob, width, height)
    return out


# -- the package ----------------------------------------------------------------------------------


def _drop(deck: Any) -> None:
    """The template's thumbnail and printer settings, by their relationships."""
    for part in (deck.part.package, deck.part):
        rels = part.rels if hasattr(part, "rels") else part._rels  # the package's own map
        for rid, rel in list(rels.items()):
            if rel.reltype in _DROPPED:
                rels.pop(rid)


def _embedder(made: Any) -> Callable[[bytes], str]:
    """A picture's bytes as an image part of the slide `made`, by python-pptx's own dedupe."""

    def embed(blob: bytes) -> str:
        _, rid = made.part.get_or_add_image_part(io.BytesIO(blob))
        return str(rid)

    return embed


def _linker(made: Any, slides: Mapping[str, Any]) -> Callable[[str], tuple[str, str]]:
    """A link's `href` as a relationship of the slide `made` (`lower.links`): `#u<NN>` jumps to
    that unit's slide, and a page is an external hyperlink."""

    def link(href: str) -> tuple[str, str]:
        if not href.startswith("#"):
            rid = made.part.relate_to(href, RELATIONSHIP_TYPE.HYPERLINK, is_external=True)
            return (str(rid), "")
        target = slides.get(href[1:])
        if target is None:
            raise TargetError(
                f"a link to {href} names no slide in this deck",
                symbol="OW_TARGET_REFERENCE_UNRESOLVED",
                fix="ow out check --stage final   # a link names #u<NN>, a unit of the deck",
            )
        return (str(made.part.relate_to(target.part, RELATIONSHIP_TYPE.SLIDE)), links.JUMP)

    return link


def _tree(made: Any) -> Any:
    """The slide's `p:spTree` (module docstring: python-pptx's private handle)."""
    return made.shapes._spTree


def _core(deck: Any, title: str, clock_ns: int) -> None:
    """`dcterms:created == dcterms:modified == clock_ns`, `cp:revision` 1, no host identity."""
    when = dt.datetime.fromtimestamp(clock_ns // 1_000_000_000, tz=dt.UTC)
    core = deck.core_properties
    core.title = title
    core.author = ""
    core.comments = ""
    core.last_modified_by = ""
    core.revision = 1
    core.created = when
    core.modified = when


def _package(deck: Any) -> bytes:
    buffer = io.BytesIO()
    deck.save(buffer)
    with zipfile.ZipFile(io.BytesIO(buffer.getvalue())) as zf:
        members = {info.filename: zf.read(info) for info in zf.infolist()}
    members["docProps/app.xml"] = _app(members["docProps/app.xml"])
    members[_PRESENTATION] = _sized(members[_PRESENTATION])
    packed = write_opc({name: _canonical(name, data) for name, data in members.items()})
    check_package(packed)
    return packed


def _canonical(name: str, data: bytes) -> bytes:
    """An XML part with every attribute map sorted."""
    if not name.endswith((".xml", ".rels")):
        return data
    root = etree.fromstring(data, _PARSER)
    for element in root.iter():
        if isinstance(element.tag, str):
            items = sorted(element.attrib.items())
            element.attrib.clear()
            element.attrib.update(items)
    return etree.tostring(root, xml_declaration=True, encoding="UTF-8", standalone=True)


def _sized(data: bytes) -> bytes:
    """The presentation, its slide size's `type` dropped (module docstring)."""
    root = etree.fromstring(data, _PARSER)
    for size in root.iter(_SLIDE_SIZE):
        size.attrib.pop("type", None)
    return etree.tostring(root, xml_declaration=True, encoding="UTF-8", standalone=True)


def _app(data: bytes) -> bytes:
    """The template's app properties, less PowerPoint's host and counts: two fixed values."""
    root = etree.fromstring(data, _PARSER)
    namespace = etree.QName(root).namespace
    for child in list(root):
        root.remove(child)
    for tag, value in _APP:
        etree.SubElement(root, f"{{{namespace}}}{tag}").text = value
    return etree.tostring(root, xml_declaration=True, encoding="UTF-8", standalone=True)
