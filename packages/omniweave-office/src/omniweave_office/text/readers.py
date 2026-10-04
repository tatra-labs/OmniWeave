"""The ten text formats `decode.text-native` routes, each read into `block` records.

One small builder, `Blocks`, writes every record, and one function per format fills it. The
records are `owdoc-fragment/1`'s `block` shape exactly as `parse.office.anydoc` writes them
(`omniweave_office.blocks`), so the host's one decoder reads both drivers:

- `os` is `{"k": "none"}` on every block and `quote` is `normalized`. A block's text is the
  format's *content*: a heading without its `#`s, an HTML paragraph with its entities decoded, a
  JSON leaf rendered as `path: value`. None of those is a byte range of the source, so no block
  carries an address, which is what the card's `origin_span = "none"` says (03:1561).
- `method` is `native`: the bytes were read by their own grammar, with no model and no OCR.
- `layer` is `body` throughout. A text file has no running header, no footnote area and no slide
  notes, so there is nothing to put on another layer.

**What each reader keeps, and what it leaves.**

- `md`: ATX and setext headings, paragraphs, bullet and ordered lists (nested by indentation),
  block quotes, fenced and indented code with its info string, pipe tables, thematic breaks, and a
  leading YAML front-matter block as code. Inline markup stays in the text as written: `**bold**`
  is searchable as written, and a `marks` layer would need a span this driver does not record.
- `txt`: paragraphs separated by blank lines, their lines kept.
- `html`, `xhtml`: headings, paragraphs, lists, block quotes, `pre` as code, tables with their
  `rowspan` and `colspan`, and `hr`. `script`, `style`, `template`, `noscript` and `head` are not
  content. A table inside a table is read as its cell's text.
- `xml`: the text of each element that has any, in document order. No DTD and no entity is
  expanded: `defusedxml` refuses both (14:520's billion-laughs and external-entity rules).
- `svg`: the `title`, `desc` and `text` elements, the only text an SVG says.
- `json`: one `path: value` paragraph per leaf. `jsonl`: one per record, its leaves joined.
- `ipynb`: markdown cells through the `md` reader, code cells as code in the kernel's language,
  and their text outputs as code with no language.
- `tsv`: one table, its first row the header.

Specified in 04-driver-system.md section 10.1 and 05-ingest-and-routing.md section 4.4
(`decode.text-native`).
"""

from __future__ import annotations

import csv
import io
import json
import re
import unicodedata
from collections.abc import Callable, Iterator, Sequence
from html.parser import HTMLParser
from typing import Any, Final

__all__ = ["READERS", "Blocks", "ReadError", "clean"]

_ORIGIN_NONE: Final[dict[str, str]] = {"k": "none"}
_CONTROL: Final = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


class ReadError(ValueError):
    """These bytes are not the format they were routed as. The driver maps it to `CORRUPT_INPUT`."""


def clean(text: str) -> str:
    """NFC, with the C0 controls other than tab and newline removed.

    NFC because 03:2991's comparison is `nfc()` and every text a store holds is in it. The controls
    because a text file that is really binary decodes into them, and a NUL in `block.text` reaches
    every Channel's tokenizer for nothing.
    """
    return unicodedata.normalize("NFC", _CONTROL.sub("", text.replace("\r\n", "\n")))


class Blocks:
    """The records one document becomes, and the counts `achieved` is computed from."""

    def __init__(self) -> None:
        self.records: list[dict[str, Any]] = []
        self.headings = 0
        self.tables = 0
        self.has_spans = False
        self._n = 0

    def add(
        self,
        kind: str,
        text: str = "",
        *,
        parent: str | None = None,
        payload: dict[str, Any] | None = None,
        cell: dict[str, int] | None = None,
    ) -> str:
        """One `block` record, returning its `tmp`. A heading is counted for `sections`."""
        self._n += 1
        tmp = f"b{self._n}"
        if kind == "heading":
            self.headings += 1
        record: dict[str, Any] = {
            "t": "block",
            "tmp": tmp,
            "parent": parent,
            "page": 0,
            "kind": kind,
            "layer": "body",
            "text": clean(text),
            "quote": "normalized",
            "trust": "extracted",
            "method": "native",
            "os": dict(_ORIGIN_NONE),
            "quad": None,
            "marks": [],
            "payload": payload,
        }
        if cell is not None:
            record["cell"] = cell
        self.records.append(record)
        return tmp

    def paragraph(self, text: str, parent: str | None = None) -> None:
        """A paragraph, unless its text is only whitespace: an empty block says nothing."""
        if text.strip():
            self.add("paragraph", text.strip(), parent=parent)

    def code(self, text: str, lang: str | None, parent: str | None = None) -> None:
        if text.strip():
            self.add(
                "code", text.rstrip("\n"), parent=parent, payload={"lang": lang} if lang else None
            )

    def table(
        self,
        rows: Sequence[Sequence[tuple[str, int, int]]],
        *,
        header_rows: int,
        parent: str | None,
    ) -> None:
        """A `table` and one `table_cell` per origin slot, each cell's text a child paragraph.

        `rows` holds `(text, row_span, col_span)` per cell in source order. The grid position of a
        cell is the first column its row has not had covered by a span from above, which is the
        HTML table model; `build_grid` derives the covered slots from the origins' spans, so they
        are not emitted (the anydoc driver's rule, INV-21).
        """
        if not any(rows):
            return
        self.tables += 1
        tmp = self.add(
            "table",
            parent=parent,
            payload={"header_rows": header_rows, "header_cols": 0, "kind": "data"},
        )
        covered: set[tuple[int, int]] = set()
        for r, row in enumerate(rows):
            c = 0
            for text, row_span, col_span in row:
                while (r, c) in covered:
                    c += 1
                self.has_spans = self.has_spans or row_span > 1 or col_span > 1
                for dr in range(row_span):
                    for dc in range(col_span):
                        covered.add((r + dr, c + dc))
                cell = self.add(
                    "table_cell",
                    parent=tmp,
                    cell={"r": r, "c": c, "row_span": row_span, "col_span": col_span},
                )
                self.paragraph(text, cell)
                c += col_span


def _list(ordered: bool, start: int, nesting: int) -> dict[str, Any]:
    """03:959's `list` payload: `ordered`, `start`, `marker_style` and `nesting_level`."""
    return {
        "ordered": ordered,
        "start": start,
        "marker_style": "decimal" if ordered else "bullet",
        "nesting_level": nesting,
    }


# ---------------------------------------------------------------------------------------------
# md
# ---------------------------------------------------------------------------------------------

_ATX: Final = re.compile(r"^ {0,3}(#{1,6})(?:[ \t]+(.*?))?(?:[ \t]+#+)?[ \t]*$")
_SETEXT: Final = re.compile(r"^ {0,3}(=+|-+)[ \t]*$")
_RULE: Final = re.compile(r"^ {0,3}([-*_])(?:[ \t]*\1){2,}[ \t]*$")
_FENCE: Final = re.compile(r"^( {0,3})(`{3,}|~{3,})[ \t]*([^`\s]*)")
_QUOTE: Final = re.compile(r"^ {0,3}> ?(.*)$")
_ITEM: Final = re.compile(r"^( *)([-*+]|\d{1,9}[.)])[ \t]+(.*)$")
_DELIMITER: Final = re.compile(r"^ {0,3}\|?[ \t]*:?-+:?[ \t]*(\|[ \t]*:?-+:?[ \t]*)*\|?[ \t]*$")


def _cells(line: str) -> list[str]:
    body = line.strip()
    body = body.removeprefix("|")
    body = body[:-1] if body.endswith("|") and not body.endswith("\\|") else body
    return [cell.strip().replace("\\|", "|") for cell in re.split(r"(?<!\\)\|", body)]


class _Markdown:
    """A line reader for the Markdown block structure. One pass, no backtracking."""

    def __init__(self, out: Blocks, parent: str | None) -> None:
        self.out = out
        self.parent = parent
        self.para: list[str] = []
        self.lists: list[dict[str, Any]] = []

    def flush(self) -> None:
        text = " ".join(line.strip() for line in self.para)
        self.para = []
        if not text:
            return
        owner = self.lists[-1]["item"] if self.lists else self.parent
        self.out.paragraph(text, owner)

    def close_lists(self, indent: int = -1) -> None:
        self.flush()
        while self.lists and self.lists[-1]["indent"] > indent:
            self.lists.pop()

    def item(self, indent: int, marker: str, text: str) -> None:
        self.flush()
        ordered = marker[0].isdigit()
        while self.lists and (
            indent < self.lists[-1]["indent"]
            or (indent == self.lists[-1]["indent"] and self.lists[-1]["ordered"] != ordered)
        ):
            self.lists.pop()
        if not self.lists or indent > self.lists[-1]["indent"]:
            owner = self.lists[-1]["item"] if self.lists else self.parent
            start = int(marker[:-1]) if ordered else 1
            tmp = self.out.add("list", parent=owner, payload=_list(ordered, start, len(self.lists)))
            self.lists.append({"indent": indent, "ordered": ordered, "list": tmp, "item": None})
        top = self.lists[-1]
        top["item"] = self.out.add("list_item", parent=top["list"])
        self.para = [text]

    def read(self, text: str) -> None:  # noqa: PLR0912, PLR0915 -- one arm per construct.
        lines = text.split("\n")
        i = 0
        if lines and lines[0].strip() == "---":
            end = next((j for j in range(1, len(lines)) if lines[j].strip() in {"---", "..."}), 0)
            if end:
                self.out.code("\n".join(lines[1:end]), "yaml", self.parent)
                i = end + 1
        while i < len(lines):
            line = lines[i]
            fence = _FENCE.match(line)
            if fence:
                self.close_lists()
                mark = fence.group(2)
                body: list[str] = []
                i += 1
                while i < len(lines) and not lines[i].strip().startswith(mark):
                    body.append(lines[i])
                    i += 1
                self.out.code("\n".join(body), fence.group(3) or None, self.parent)
                i += 1
                continue
            if not line.strip():
                self.flush()
                i += 1
                continue
            heading = _ATX.match(line)
            if heading:
                self.close_lists()
                self.out.add(
                    "heading",
                    (heading.group(2) or "").strip(),
                    parent=self.parent,
                    payload={"level": len(heading.group(1))},
                )
                i += 1
                continue
            setext = _SETEXT.match(line)
            if setext and self.para and not self.lists:
                title = " ".join(part.strip() for part in self.para)
                self.para = []
                level = 1 if setext.group(1)[0] == "=" else 2
                self.out.add("heading", title, parent=self.parent, payload={"level": level})
                i += 1
                continue
            if _RULE.match(line):
                self.close_lists()
                self.out.add("rule", parent=self.parent)
                i += 1
                continue
            item = _ITEM.match(line)
            if item:
                self.item(len(item.group(1)), item.group(2), item.group(3))
                i += 1
                continue
            if self.lists and line.startswith(" "):
                self.para.append(line)
                i += 1
                continue
            quote = _QUOTE.match(line)
            if quote:
                self.close_lists()
                quoted: list[str] = []
                while i < len(lines) and (match := _QUOTE.match(lines[i])):
                    quoted.append(match.group(1))
                    i += 1
                holder = self.out.add("blockquote", parent=self.parent)
                _Markdown(self.out, holder).read("\n".join(quoted))
                continue
            if "|" in line and i + 1 < len(lines) and _DELIMITER.match(lines[i + 1]):
                self.close_lists()
                rows = [_cells(line)]
                i += 2
                while i < len(lines) and "|" in lines[i] and lines[i].strip():
                    rows.append(_cells(lines[i]))
                    i += 1
                width = len(rows[0])
                grid = [[(cell, 1, 1) for cell in (row + [""] * width)[:width]] for row in rows]
                self.out.table(grid, header_rows=1, parent=self.parent)
                continue
            if line.startswith("    ") and not self.para and not self.lists:
                body = []
                while i < len(lines) and (lines[i].startswith("    ") or not lines[i].strip()):
                    body.append(lines[i][4:])
                    i += 1
                self.out.code("\n".join(body), None, self.parent)
                continue
            if self.lists:
                self.close_lists()
            self.para.append(line)
            i += 1
        self.close_lists()


def markdown(text: str, out: Blocks, parent: str | None = None) -> None:
    _Markdown(out, parent).read(text)


def plain(text: str, out: Blocks) -> None:
    """Paragraphs separated by blank lines, each keeping its own line breaks."""
    for chunk in re.split(r"\n[ \t]*\n", text):
        out.paragraph("\n".join(line.rstrip() for line in chunk.strip("\n").split("\n")))


# ---------------------------------------------------------------------------------------------
# html, xhtml
# ---------------------------------------------------------------------------------------------

_SKIPPED: Final = frozenset({"script", "style", "template", "noscript", "head"})
_FLOW: Final = frozenset(
    {
        "p", "div", "section", "article", "header", "footer", "main", "aside", "nav", "dt", "dd",
        "figcaption", "caption", "address", "details", "summary", "form", "fieldset", "body",
    }
)  # fmt: skip
_HEADINGS: Final = {f"h{n}": n for n in range(1, 7)}


class _Html(HTMLParser):
    """HTML's block structure from `html.parser`'s event stream. Entities are decoded by it."""

    def __init__(self, out: Blocks) -> None:
        super().__init__(convert_charrefs=True)
        self.out = out
        self.text: list[str] = []
        self.containers: list[str | None] = [None]
        self.lists: list[str] = []
        self.skip = 0
        self.pre = 0
        self.heading = 0
        self.table_depth = 0
        self.rows: list[list[tuple[str, int, int]]] = []
        self.cell: dict[str, Any] | None = None

    def flush(self) -> None:
        raw = "".join(self.text)
        self.text = []
        if self.cell is not None:
            self.cell["text"].append(raw)
            return
        if self.pre:
            self.out.code(raw.strip("\n"), None, self.containers[-1])
            return
        text = " ".join(raw.split())
        if not text:
            return
        if self.heading:
            self.out.add(
                "heading", text, parent=self.containers[-1], payload={"level": self.heading}
            )
        else:
            self.out.paragraph(text, self.containers[-1])

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:  # noqa: PLR0912
        if tag in _SKIPPED:
            self.skip += 1
            return
        if self.skip:
            return
        if self.table_depth and tag not in {"table", "tr", "td", "th"}:
            if tag == "br":
                self.text.append(" ")
            return
        if tag == "table":
            self.table_depth += 1
            if self.table_depth == 1:
                self.flush()
                self.rows = []
            return
        if self.table_depth > 1:
            return
        if tag == "tr" and self.table_depth:
            self._close_cell()
            self.rows.append([])
        elif tag in {"td", "th"} and self.table_depth:
            self._close_cell()
            if not self.rows:
                self.rows.append([])
            spans = dict(attrs)
            self.cell = {
                "text": [],
                "rows": _span(spans.get("rowspan")),
                "cols": _span(spans.get("colspan")),
            }
        elif tag in _HEADINGS:
            self.flush()
            self.heading = _HEADINGS[tag]
        elif tag == "pre":
            self.flush()
            self.pre += 1
        elif tag in {"ul", "ol"}:
            self.flush()
            start = _span(dict(attrs).get("start")) if tag == "ol" else 1
            payload = _list(tag == "ol", start, len(self.lists))
            self.lists.append(self.out.add("list", parent=self.containers[-1], payload=payload))
        elif tag == "li":
            self.flush()
            owner = self.lists[-1] if self.lists else self.containers[-1]
            self.containers.append(self.out.add("list_item", parent=owner))
        elif tag == "blockquote":
            self.flush()
            self.containers.append(self.out.add("blockquote", parent=self.containers[-1]))
        elif tag == "hr":
            self.flush()
            self.out.add("rule", parent=self.containers[-1])
        elif tag == "br":
            self.text.append("\n" if self.pre else " ")
        elif tag in _FLOW:
            self.flush()

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.handle_starttag(tag, attrs)
        if tag not in {"br", "hr"}:
            self.handle_endtag(tag)

    def handle_endtag(self, tag: str) -> None:
        if tag in _SKIPPED:
            self.skip = max(0, self.skip - 1)
            return
        if self.skip:
            return
        if tag == "table" and self.table_depth:
            self.table_depth -= 1
            if not self.table_depth:
                self._close_cell()
                header = 1 if self.rows and len(self.rows) > 1 else 0
                self.out.table(self.rows, header_rows=header, parent=self.containers[-1])
                self.rows = []
            return
        if self.table_depth:
            if tag in {"td", "th"} and self.table_depth == 1:
                self._close_cell()
            return
        if tag in _HEADINGS and self.heading:
            self.flush()
            self.heading = 0
        elif tag == "pre" and self.pre:
            self.flush()
            self.pre -= 1
        elif tag in {"ul", "ol"} and self.lists:
            self.flush()
            self.lists.pop()
        elif tag in {"li", "blockquote"} and len(self.containers) > 1:
            self.flush()
            self.containers.pop()
        elif tag in _FLOW:
            self.flush()

    def handle_data(self, data: str) -> None:
        if not self.skip:
            self.text.append(data)

    def _close_cell(self) -> None:
        if self.cell is None:
            return
        self.cell["text"].append("".join(self.text))
        self.text = []
        text = " ".join("".join(self.cell["text"]).split())
        self.rows[-1].append((text, self.cell["rows"], self.cell["cols"]))
        self.cell = None

    def finish(self) -> None:
        self.close()
        self._close_cell()
        if self.table_depth and self.rows:
            self.out.table(self.rows, header_rows=0, parent=self.containers[-1])
        self.flush()


def _span(value: str | None) -> int:
    """A `rowspan`, `colspan` or `start` attribute as a positive integer, 1 when it is not one."""
    try:
        return max(1, min(int(str(value).strip()), 1000))
    except ValueError:
        return 1


def html(text: str, out: Blocks) -> None:
    parser = _Html(out)
    parser.feed(text)
    parser.finish()


# ---------------------------------------------------------------------------------------------
# xml, svg
# ---------------------------------------------------------------------------------------------


def _tree(raw: bytes) -> Any:
    """`defusedxml`'s parse: no DTD, no entity, no external reference. Each is a `ReadError`."""
    from defusedxml import DefusedXmlException  # noqa: PLC0415 -- the two XML readers only
    from defusedxml.ElementTree import ParseError, fromstring  # noqa: PLC0415

    try:
        return fromstring(raw, forbid_dtd=True, forbid_entities=True, forbid_external=True)
    except DefusedXmlException as exc:
        msg = f"this XML declares what the reader refuses (14:520): {type(exc).__name__}"
        raise ReadError(msg) from None
    except ParseError as exc:
        msg = f"these bytes are not well-formed XML: {exc}"
        raise ReadError(msg) from None


def _local(tag: object) -> str:
    return str(tag).rsplit("}", 1)[-1] if isinstance(tag, str) else ""


def xml(raw: bytes, out: Blocks) -> None:
    for element in _tree(raw).iter():
        if not isinstance(element.tag, str):
            continue
        for text in (element.text, element.tail):
            out.paragraph(" ".join((text or "").split()))


def svg(raw: bytes, out: Blocks) -> None:
    for element in _tree(raw).iter():
        name = _local(element.tag)
        if name in {"title", "desc", "text"}:
            out.paragraph(" ".join("".join(element.itertext()).split()))


# ---------------------------------------------------------------------------------------------
# json, jsonl, ipynb, tsv
# ---------------------------------------------------------------------------------------------


def _leaves(value: object, path: str = "") -> Iterator[tuple[str, str]]:
    if isinstance(value, dict):
        for key, child in value.items():
            yield from _leaves(child, f"{path}.{key}" if path else str(key))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            yield from _leaves(child, f"{path}[{index}]")
    else:
        rendered = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)
        yield path or "$", str(rendered)


def _loads(text: str, where: str = "") -> object:
    try:
        return json.loads(text)
    except (ValueError, RecursionError) as exc:
        msg = (
            f"{where}not JSON: {exc}"
            if not isinstance(exc, RecursionError)
            else (f"{where}nested deeper than this reader follows")
        )
        raise ReadError(msg) from None


def json_doc(text: str, out: Blocks) -> None:
    for path, value in _leaves(_loads(text)):
        out.paragraph(f"{path}: {value}")


def jsonl(text: str, out: Blocks) -> None:
    for number, line in enumerate(text.split("\n"), start=1):
        if line.strip():
            record = _loads(line, f"line {number} is ")
            out.paragraph("; ".join(f"{path}: {value}" for path, value in _leaves(record)))


def notebook(text: str, out: Blocks) -> None:
    """nbformat 4: markdown cells as Markdown, code cells as code, text outputs as code."""
    document = _loads(text)
    if not isinstance(document, dict) or not isinstance(document.get("cells"), list):
        msg = "a notebook is a JSON object with a `cells` list (nbformat 4)"
        raise ReadError(msg)
    meta = _object(document.get("metadata"))
    named = _object(meta.get("language_info")).get("name")
    language = str(named or _object(meta.get("kernelspec")).get("language") or "") or None
    for cell in document["cells"]:
        if not isinstance(cell, dict):
            continue
        source = _joined(cell.get("source"))
        kind = cell.get("cell_type")
        if kind == "markdown":
            markdown(source, out)
        elif kind == "code":
            out.code(source, language)
            for output in cell.get("outputs") or ():
                if isinstance(output, dict):
                    out.code(_output_text(output), None)
        else:
            out.code(source, None)


def _object(value: object) -> dict[str, Any]:
    """A JSON object as a dict, or an empty one: notebook metadata is optional at every level."""
    return value if isinstance(value, dict) else {}


def _joined(source: object) -> str:
    if isinstance(source, list):
        return "".join(str(part) for part in source)
    return "" if source is None else str(source)


def _output_text(output: dict[str, Any]) -> str:
    if output.get("output_type") == "stream":
        return _joined(output.get("text"))
    data = output.get("data")
    if isinstance(data, dict) and "text/plain" in data:
        return _joined(data["text/plain"])
    return ""


def tsv(text: str, out: Blocks) -> None:
    rows = [row for row in csv.reader(io.StringIO(text), delimiter="\t") if any(row)]
    width = max((len(row) for row in rows), default=0)
    grid = [[(cell, 1, 1) for cell in (row + [""] * width)[:width]] for row in rows]
    out.table(grid, header_rows=1 if len(grid) > 1 else 0, parent=None)


READERS: Final[dict[str, tuple[bool, Callable[..., None]]]] = {
    "md": (False, markdown),
    "txt": (False, plain),
    "html": (False, html),
    "xhtml": (False, html),
    "xml": (True, xml),
    "svg": (True, svg),
    "json": (False, json_doc),
    "jsonl": (False, jsonl),
    "ipynb": (False, notebook),
    "tsv": (False, tsv),
}
"""Format token -> `(reads the raw bytes, reader)`. The two XML readers take bytes so the XML
declaration's own `encoding` is honoured; the others take the decoded text."""
