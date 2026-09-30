"""Pages added to a PDF, for the paired-damage suite's `inflate` Injector. D644.

13:1294's `inflate` *"generates a fixture exactly one row above a `[limits]` value"*. For a PDF the
row is a page: `gate.too-many-parts` refuses `unit.part_count > [ingest] max_parts`, and a PDF's
`unit.part_count` is `pdfium`'s page count (05:2199). So `pad_pages` takes a pristine document to
exactly `to_pages` pages, and the Injector sets the cap one below.

**An incremental update, and the pristine bytes untouched.** ISO 32000-1 §7.5.6: the original file
is kept byte for byte, and what follows it is the new page objects, a new version of the `/Pages`
node listing them, a cross-reference section for those objects alone, and a trailer whose `/Prev`
names the original one. Every reader follows `/Prev`, detection's trailer check reads the last
`startxref` (D641), and the damage is the pages and nothing else.

**Each added page is a copy of the last one**, `/Contents` and `/Resources` included. A blank page
would be a page with no text layer, which routing escalates to OCR, and the pair would then measure
`strip_text_layer` rather than this Injector. A copy has the pristine page's text, so the document
answers what it answered.

**The shape it takes is the shape it refuses**, as `pdfcrypt` does: a classic xref table, and a
page tree one level deep whose kids are pages. Anything else raises `ValueError` naming what it
found, because padding a tree it did not understand would write a file whose page count is a guess.
"""

from __future__ import annotations

import re
from typing import Final

__all__ = ["pad_pages", "page_count"]

_OBJECT: Final = re.compile(rb"(\d+) (\d+) obj\s(.*?)\sendobj", re.DOTALL)
_REF: Final = rb"(\d+)\s+(\d+)\s+R"
_ROOT: Final = re.compile(rb"/Root\s+" + _REF)
_INFO: Final = re.compile(rb"/Info\s+" + _REF)
_ID: Final = re.compile(rb"/ID\s*\[[^\]]*\]")
_SIZE: Final = re.compile(rb"/Size\s+(\d+)")
_PAGES: Final = re.compile(rb"/Pages\s+" + _REF)
_KIDS: Final = re.compile(rb"/Kids\s*\[([^\]]*)\]")
_COUNT: Final = re.compile(rb"/Count\s+(\d+)")
_STARTXREF: Final = re.compile(rb"startxref\s+(\d+)\s+%%EOF\s*$")


def _tree(data: bytes) -> tuple[dict[int, tuple[int, bytes]], bytes, int, int]:
    """The objects, the last trailer, the `/Pages` node's number and its kids' count."""
    for marker, what in (
        (b"/ObjStm", "an object stream"),
        (b"/XRef", "a cross-reference stream"),
        (b"/Encrypt", "an encryption dictionary"),
    ):
        if marker in data:
            msg = f"pad_pages writes classic-xref PDFs, and this one has {what}"
            raise ValueError(msg)
    if not data.startswith(b"%PDF-") or b"\nxref" not in data or b"trailer" not in data:
        msg = "pad_pages needs a PDF with a classic xref table and a trailer"
        raise ValueError(msg)
    objects = {
        int(match.group(1)): (int(match.group(2)), match.group(3))
        for match in _OBJECT.finditer(data)
    }
    trailer = data[data.rindex(b"trailer") :]
    root = _ROOT.search(trailer)
    catalog = objects.get(int(root.group(1))) if root else None
    pages = _PAGES.search(catalog[1]) if catalog else None
    if pages is None or int(pages.group(1)) not in objects:
        msg = "pad_pages found no /Root catalog naming a /Pages node"
        raise ValueError(msg)
    number = int(pages.group(1))
    kids = _KIDS.search(objects[number][1])
    if kids is None:
        msg = "pad_pages found a /Pages node with no /Kids"
        raise ValueError(msg)
    refs = [int(one.group(1)) for one in re.finditer(_REF, kids.group(1))]
    for ref in refs:
        body = objects.get(ref, (0, b""))[1]
        if not re.search(rb"/Type\s*/Page\b(?!s)", body):
            msg = f"pad_pages writes a page tree one level deep, and kid {ref} is not a page"
            raise ValueError(msg)
    return objects, trailer, number, len(refs)


def page_count(data: bytes) -> int:
    """How many pages a PDF `pad_pages` could pad has: its one-level tree's kids."""
    return _tree(data)[3]


def pad_pages(data: bytes, *, to_pages: int) -> bytes:
    """`data` with copies of its last page appended until it has `to_pages` pages.

    Raises `ValueError` for a PDF this does not write (see the module docstring), or one that
    already has `to_pages` pages or more, since that is not a fixture one row above anything.
    """
    objects, trailer, number, count = _tree(data)
    if count >= to_pages:
        msg = f"pad_pages takes a PDF to {to_pages} pages, and this one has {count} already"
        raise ValueError(msg)
    generation, node = objects[number]
    kids = _KIDS.search(node)
    size = _SIZE.search(trailer)
    prev = _STARTXREF.search(data)
    if kids is None or size is None or prev is None:
        msg = "pad_pages needs a /Size in the trailer and a final startxref"
        raise ValueError(msg)
    last = int(list(re.finditer(_REF, kids.group(1)))[-1].group(1))
    copy = objects[last][1]
    first = max(int(size.group(1)), max(objects) + 1)
    added = list(range(first, first + to_pages - count))

    out = bytearray(data if data.endswith(b"\n") else data + b"\n")
    offsets: dict[int, int] = {}
    for new in added:
        offsets[new] = len(out)
        out += f"{new} 0 obj\n".encode() + copy + b"\nendobj\n"
    listed = kids.group(1).strip() + b"".join(f" {new} 0 R".encode() for new in added)
    grown = node[: kids.start(1)] + listed + node[kids.end(1) :]
    grown = _COUNT.sub(f"/Count {to_pages}".encode(), grown, count=1)
    offsets[number] = len(out)
    out += f"{number} {generation} obj\n".encode() + grown + b"\nendobj\n"

    xref = len(out)
    out += f"xref\n{number} 1\n{offsets[number]:010d} {generation:05d} n \n".encode()
    out += f"{first} {len(added)}\n".encode()
    out += b"".join(f"{offsets[new]:010d} 00000 n \n".encode() for new in added)
    root = _ROOT.search(trailer)
    info = _INFO.search(trailer)
    found_id = _ID.search(trailer)
    assert root is not None
    out += (
        f"trailer\n<< /Size {first + len(added)} /Root {int(root.group(1))} "
        f"{int(root.group(2))} R".encode()
        + (f" /Info {int(info.group(1))} {int(info.group(2))} R".encode() if info else b"")
        + (b" " + found_id.group(0) if found_id else b"")
        + f" /Prev {int(prev.group(1))} >>\nstartxref\n{xref}\n%%EOF\n".encode()
    )
    return bytes(out)
