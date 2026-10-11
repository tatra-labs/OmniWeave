"""One compile: preflight, the walk over every unit, then a package whose parts are a function of
the IL, the assets, the Brief and the job's clock alone (09 sections 5.1, 6 and 12.3).

python-docx builds the document from its own template, and this module decides what reaches the
package: the template's thumbnail, its bibliography `customXml` item and `stylesWithEffects` are
dropped by dropping their relationships, every `w:rsid*` and `w:rsids` is stripped, `dcterms`
are the job's clock, `cp:revision` is 1 and the app properties are fixed. Every attribute map is
sorted, and `write_opc()` decides the member order and every ZIP field.
"""

from __future__ import annotations

import datetime as dt
import io
import zipfile
from collections.abc import Callable, Mapping, Sequence
from types import MappingProxyType
from typing import TYPE_CHECKING, Final, cast

import docx
from docx.enum.section import WD_SECTION
from docx.enum.style import WD_STYLE_TYPE
from docx.image.exceptions import UnrecognizedImageError
from docx.image.image import Image
from docx.opc.constants import RELATIONSHIP_TYPE
from docx.oxml.ns import qn
from docx.shared import Inches, Mm, Pt, RGBColor
from lxml import etree  # type: ignore[attr-defined] -- lxml ships no stubs
from omniweave_core.errors import TargetError
from omniweave_core.out.carrier import parse_selector
from omniweave_core.out.constructs import ConstructTable, Disposition
from omniweave_core.out.opc import write_opc

from omniweave_target_docx.lower import blocks, ids, inline, lists, manual, media, tables, units
from omniweave_target_docx.lower._emit import (
    CODE_FONT,
    Emitter,
    refuse_unmapped,
    rows_of,
    unmapped,
    walk,
)
from omniweave_target_docx.lower._numbering import Numbering

if TYPE_CHECKING:
    from docx.document import Document
    from docx.styles.style import CharacterStyle, ParagraphStyle
    from omniweave_core.out import AssetLedger, CarrierDoc, ILBundle, Plan
    from omniweave_core.out.carrier import CarrierNode

__all__ = ["FAMILIES", "PAGES", "build", "page_of"]

FAMILIES: Final = MappingProxyType(
    {
        f"lower.{module.__name__.rpartition('.')[2]}": module
        for module in (blocks, ids, inline, lists, manual, media, tables, units)
    }
)
"""The modules a `maps_to` may name, imported here and never by name (INV-4)."""
PAGES: Final = MappingProxyType(
    {
        "a4": (Mm(210), Mm(297)),
        "a5": (Mm(148), Mm(210)),
        "letter": (Inches(8.5), Inches(11)),
        "legal": (Inches(8.5), Inches(14)),
    }
)
"""The Brief's `## canvas - format` names a page; any other value keeps the template's letter."""
_DROPPED: Final = frozenset({RELATIONSHIP_TYPE.THUMBNAIL, RELATIONSHIP_TYPE.CUSTOM_XML})
_DROPPED_SUFFIX: Final = "/stylesWithEffects"
"""Word 2010's duplicate of `styles.xml`, which python-docx has no constant for."""
_RSIDS: Final = qn("w:rsids")
_RSID: Final = qn("w:rsid")
"""A style's `w:rsid` element, and the prefix of every `w:rsid*` attribute's qualified name."""
_APP: Final = (("Application", "omniweave-target-docx"), ("DocSecurity", "0"))
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
) -> bytes:
    """Preflight, then every unit in Plan order, then the package's bytes."""
    _rosters(plan, il, max_units)
    roots = [carrier(u.il_path, il.text(u.il_path)).root() for u in plan.units]
    rows = rows_of(table)
    refuse_unmapped(unmapped(roots, rows, FAMILIES))
    _normalized(roots, table, normalizers)
    assets = _assets(roots, ledger)
    document = _document(plan)
    section = document.sections[0]
    width = int(section.page_width or 0) - int(section.left_margin or 0)
    em = Emitter(
        document,
        rows,
        FAMILIES,
        assets,
        Numbering(document),
        width - int(section.right_margin or 0),
    )
    for n, root in enumerate(roots):
        if n:
            em.end_paragraph()
            document.add_section(WD_SECTION.CONTINUOUS)
        em.block(root)
    _core(document, plan.slug, clock_ns)
    return _package(document)


def page_of(format_: str | None) -> str | None:
    """The page the Brief's canvas names, or `None` when it names none `PAGES` has."""
    key = (format_ or "").strip().lower()
    return key if key in PAGES else None


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


def _normalized(
    roots: Sequence[CarrierNode],
    table: ConstructTable,
    normalizers: Mapping[str, Callable[[str], str]],
) -> None:
    """09 section 5.3: a value a `normalize` row would rewrite does not reach the package."""
    found: list[str] = []
    for row in table.rows:
        if row.disposition is not Disposition.NORMALIZE:
            continue
        name = parse_selector(row.selector, table.carrier).name
        fix = normalizers[row.normalizer or ""]
        for root in roots:
            for node in walk(root):
                value = node.attr(name)
                if value is not None and fix(value) != value:
                    found.append(f"{row.id} at {node.at}")
    if found:
        raise TargetError(
            f"{len(found)} value(s) are not in canonical form: {', '.join(found[:3])}",
            symbol="OW_TARGET_NORMALIZE_AT_COMPILE",
            fix="ow out normalize   # then check and compile again",
        )


def _assets(roots: Sequence[CarrierNode], ledger: AssetLedger) -> dict[str, bytes]:
    """Check 2: every picture's slot is frozen, and its bytes are an image Word can hold."""
    out: dict[str, bytes] = {}
    for root in roots:
        for node in walk(root):
            slot = node.attr("src") if node.tag == "html|img" else None
            if slot is None or slot in out:
                continue
            with ledger.open(slot) as stream:
                blob = stream.read()
            try:
                Image.from_blob(blob)
            except UnrecognizedImageError:
                raise TargetError(
                    f"{slot} at {node.at} is not an image WordprocessingML can hold: PNG, JPEG, "
                    "GIF, BMP or TIFF",
                    symbol="OW_TARGET_ASSET_FORMAT",
                    fix="ow out assets --slot " + slot,
                ) from None
            out[slot] = blob
    return out


# -- the document ---------------------------------------------------------------------------------


def _document(plan: Plan) -> Document:
    """python-docx's template, less its baggage, with owflow/1's styles and the Brief's page."""
    document = docx.Document()
    package = document.part.package
    for rels in (package.rels if package is not None else {}, document.part.rels):
        for rid, rel in list(rels.items()):
            if rel.reltype in _DROPPED or rel.reltype.endswith(_DROPPED_SUFFIX):
                rels.pop(rid)
    styles = document.styles
    link = cast("CharacterStyle", styles.add_style("Hyperlink", WD_STYLE_TYPE.CHARACTER))
    link.font.underline = True
    link.font.color.rgb = RGBColor(0x05, 0x63, 0xC1)
    code = cast("ParagraphStyle", styles.add_style("Code Block", WD_STYLE_TYPE.PARAGRAPH))
    code.base_style = cast("ParagraphStyle", styles["Normal"])
    code.font.name = CODE_FONT
    code.font.size = Pt(10)
    code.paragraph_format.space_after = Pt(0)
    page = page_of(plan.brief.value("canvas", "format"))
    if page is not None:
        section = document.sections[0]
        section.page_width, section.page_height = PAGES[page]
    return document


def _core(document: Document, title: str, clock_ns: int) -> None:
    """`dcterms:created == dcterms:modified == clock_ns`, `cp:revision` 1, no host identity."""
    when = dt.datetime.fromtimestamp(clock_ns // 1_000_000_000, tz=dt.UTC)
    core = document.core_properties
    core.title = title
    core.author = ""
    core.comments = ""
    core.last_modified_by = ""
    core.revision = 1
    core.created = when
    core.modified = when


def _package(document: Document) -> bytes:
    buffer = io.BytesIO()
    document.save(buffer)
    with zipfile.ZipFile(io.BytesIO(buffer.getvalue())) as zf:
        members = {info.filename: zf.read(info) for info in zf.infolist()}
    members["docProps/app.xml"] = _app(members["docProps/app.xml"])
    return write_opc({name: _canonical(name, data) for name, data in members.items()})


def _canonical(name: str, data: bytes) -> bytes:
    """An XML part with no `w:rsid*`, no `w:rsids` and every attribute map sorted."""
    if not name.endswith((".xml", ".rels")):
        return data
    root = etree.fromstring(data, _PARSER)
    for element in list(root.iter()):
        if not isinstance(element.tag, str):
            continue
        if element.tag in {_RSIDS, _RSID}:  # settings' list, and a style's own `w:rsid`
            element.getparent().remove(element)
            continue
        items = sorted((k, v) for k, v in element.attrib.items() if not k.startswith(_RSID))
        element.attrib.clear()
        element.attrib.update(items)
    return etree.tostring(root, xml_declaration=True, encoding="UTF-8", standalone=True)


def _app(data: bytes) -> bytes:
    """The template's app properties, less Word's host and counts: two fixed values."""
    root = etree.fromstring(data, _PARSER)
    namespace = etree.QName(root).namespace
    for child in list(root):
        root.remove(child)
    for tag, text in _APP:
        etree.SubElement(root, f"{{{namespace}}}{tag}").text = text
    return etree.tostring(root, xml_declaration=True, encoding="UTF-8", standalone=True)
