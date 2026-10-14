"""Tables in a candidate's text, as grids: markdown pipe tables and HTML tables. **D826.**

13-quality.md section 8.1's `table` assertion is olmOCR-Bench's `TableTest`, and it tests
*"a relation, not a string"*: a target cell, and the cells `up`, `down`, `left` and `right` of it,
and its `top_heading` and `left_heading`. It must pass *"whether the tool emitted a markdown table
or an HTML table"* (mine-parse A4.7: `parse_markdown_tables` plus an HTML parser), because the
text evaluator compares marker's `<table>` with a VLM's markdown. This module turns a candidate's
text into the grids those relations are read from; `assertions.evaluate_text()` reads them.

## Rulings

1. **A markdown table is a run of lines that start with `|`, its second line a separator** of
   dashes and colons (`|---|:--:|`). The separator is not a row. Each row's cells are split on an
   unescaped `|` and stripped, the outer pipes' empty cells dropped, and a short row padded with
   empty cells to the widest.
2. **An HTML table is a `<table>` element**, read by the standard library's `HTMLParser`: `<tr>`
   rows of `<td>` and `<th>` cells, their text joined with whitespace collapsed, their tags dropped.
   A nested table is a table of its own, and its text is not its outer cell's.
3. **A span fills every slot it covers with its text.** `rowspan` and `colspan` expand the cell
   over the grid, so the cell below a two-row cell reads that cell as `up`, which is what a reader
   of the rendered table sees. A malformed span counts as 1.
4. **Grids come back in the order their tables start in the text**, markdown and HTML together.

Specified in 13-quality.md section 8.1 and `_plan/_notes/mine-parse.md` section A4.7.
"""

from __future__ import annotations

import re
from html.parser import HTMLParser
from typing import Final

__all__ = ["Grid", "html_tables", "markdown_tables", "tables"]

Grid = tuple[tuple[str, ...], ...]
"""Rows of cell texts, every row as wide as the widest, spans expanded."""

_SEPARATOR: Final = re.compile(r"^\|?\s*:?-+:?\s*(\|\s*:?-+:?\s*)*\|?$")
_SPLIT: Final = re.compile(r"(?<!\\)\|")


def tables(text: str) -> tuple[Grid, ...]:
    """Every table in `text`, markdown and HTML, in the order they start (ruling 4)."""
    found = [*_markdown(text), *_html(text)]
    return tuple(grid for _, grid in sorted(found, key=lambda item: item[0]))


def markdown_tables(text: str) -> tuple[Grid, ...]:
    """Ruling 1: the pipe tables alone."""
    return tuple(grid for _, grid in _markdown(text))


def html_tables(text: str) -> tuple[Grid, ...]:
    """Rulings 2 and 3: the HTML tables alone."""
    return tuple(grid for _, grid in _html(text))


def _markdown(text: str) -> list[tuple[int, Grid]]:
    lines = text.split("\n")
    offsets, at = [], 0
    for line in lines:
        offsets.append(at)
        at += len(line) + 1
    out: list[tuple[int, Grid]] = []
    i = 0
    while i < len(lines):
        header = lines[i].strip()
        if header.startswith("|") and i + 1 < len(lines) and _SEPARATOR.match(lines[i + 1].strip()):
            block = [lines[i]]
            j = i + 2
            while j < len(lines) and lines[j].strip().startswith("|"):
                block.append(lines[j])
                j += 1
            out.append((offsets[i], _pad([_cells(row) for row in block])))
            i = j
        else:
            i += 1
    return out


def _html(text: str) -> list[tuple[int, Grid]]:
    reader = _Reader(text)
    reader.feed(text)
    reader.close()
    return reader.done


def _cells(row: str) -> list[str]:
    parts = [part.strip().replace("\\|", "|") for part in _SPLIT.split(row.strip())]
    if parts and parts[0] == "":
        parts = parts[1:]
    if parts and parts[-1] == "":
        parts = parts[:-1]
    return parts


def _pad(rows: list[list[str]]) -> Grid:
    width = max((len(row) for row in rows), default=0)
    return tuple(tuple(row + [""] * (width - len(row))) for row in rows)


class _Table:
    """One open `<table>`: its rows of `(text, rowspan, colspan)` cells, and where it began."""

    def __init__(self, start: int) -> None:
        self.start = start
        self.rows: list[list[tuple[str, int, int]]] = []
        self.cell: list[str] | None = None
        self.span: tuple[int, int] = (1, 1)

    def grid(self) -> Grid:
        """Ruling 3: place every cell, filling each slot its spans cover."""
        slots: dict[tuple[int, int], str] = {}
        for r, row in enumerate(self.rows):
            c = 0
            for text, rowspan, colspan in row:
                while (r, c) in slots:
                    c += 1
                for dr in range(rowspan):
                    for dc in range(colspan):
                        slots[r + dr, c + dc] = text
                c += colspan
        if not slots:
            return ()
        height = max(r for r, _ in slots) + 1
        width = max(c for _, c in slots) + 1
        return tuple(tuple(slots.get((r, c), "") for c in range(width)) for r in range(height))


class _Reader(HTMLParser):
    """Rulings 2 and 3 over one candidate's text."""

    def __init__(self, text: str) -> None:
        super().__init__(convert_charrefs=True)
        self._offsets = [0]
        for line in text.split("\n"):
            self._offsets.append(self._offsets[-1] + len(line) + 1)
        self._stack: list[_Table] = []
        self.done: list[tuple[int, Grid]] = []

    def _position(self) -> int:
        line, column = self.getpos()
        return self._offsets[line - 1] + column

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "table":
            self._stack.append(_Table(self._position()))
            return
        if not self._stack:
            return
        table = self._stack[-1]
        if tag == "tr":
            table.rows.append([])
        elif tag in ("td", "th"):
            if not table.rows:
                table.rows.append([])
            values = dict(attrs)
            table.cell = []
            table.span = (_span(values.get("rowspan")), _span(values.get("colspan")))

    def handle_endtag(self, tag: str) -> None:
        if not self._stack:
            return
        table = self._stack[-1]
        if tag in ("td", "th") and table.cell is not None:
            text = " ".join("".join(table.cell).split())
            table.rows[-1].append((text, *table.span))
            table.cell = None
        elif tag == "table":
            self._stack.pop()
            self.done.append((table.start, table.grid()))

    def handle_data(self, data: str) -> None:
        if self._stack and self._stack[-1].cell is not None:
            self._stack[-1].cell.append(data)


def _span(value: str | None) -> int:
    """Ruling 3: a positive integer, or 1."""
    try:
        return max(1, int(value or 1))
    except ValueError:
        return 1
