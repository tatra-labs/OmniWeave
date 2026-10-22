#!/usr/bin/env python3
"""Generate `fixtures/store/golden-queries.jsonl`, `ow bench query`'s fixed query set. **D915.**

12-performance.md section 7.4 names the file and section 7.1 the subject it feeds: *"per-Channel
and end-to-end p50/p95/p99 ... generated stores + `fixtures/store/golden-queries.jsonl`"*. The
generated store is `gen_5000p_pdf.py`'s document, so the queries are written from that generator's
own text functions -- `heading_text`, `body_text` and `cell_text` -- and never from a store or a
parse: the query set is fixed by the fixture, not by what retrieval happens to return.

Five kinds, eight queries each, forty in all:

| kind | what it asks | the Channel it leans on |
|---|---|---|
| `heading` | an Article heading, verbatim | structural and lexical |
| `phrase` | three consecutive words of a body line | lexical |
| `cell` | one table cell's id, `R3C4-0271` | exact |
| `words` | two words from different paragraphs of one page | lexical, ranked |
| `absent` | words no page holds | every Channel, and the absence gates |

Every page drawn is at most `MAX_PAGE`, so each query has its answer in every store the bench
builds from `--pages MAX_PAGE` up: a scale that dropped the page a query names would measure an
absence, not a lookup.

Usage:

    uv run python fixtures/gen/gen_golden_queries.py           # verify the committed file
    uv run python fixtures/gen/gen_golden_queries.py --write   # (re)write it

Specified in 12-performance.md sections 7.1 and 7.4.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Final

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import gen_5000p_pdf as pdf  # noqa: E402

OUT: Final = HERE.parent / "store" / "golden-queries.jsonl"
SCHEMA: Final = "omniweave.golden-queries/1"
PER_KIND: Final = 8
MAX_PAGE: Final = 200
"""The highest page any query names, so `--pages 200` is the smallest store every query fits."""
ABSENT: Final = (
    "quantum entanglement",
    "photosynthesis chlorophyll",
    "volcanic eruption",
    "saxophone improvisation",
    "glacier moraine",
    "orbital mechanics",
    "medieval tapestry",
    "coral reef bleaching",
)
"""Words outside `gen_5000p_pdf.WORDS`, so no page of any scale holds them."""


def _page(n: int) -> int:
    """The n-th page drawn: spread over 1..MAX_PAGE by a stride coprime to it."""
    return 1 + (n * 37) % MAX_PAGE


def queries() -> list[dict[str, object]]:
    """The forty, in a fixed order."""
    out: list[dict[str, object]] = []
    for n in range(PER_KIND):
        page = _page(n)
        out.append({"id": f"heading-{n}", "kind": "heading", "page": page,
                    "text": pdf.heading_text(page)})  # fmt: skip
    for n in range(PER_KIND):
        page = _page(n + PER_KIND)
        words = pdf.body_text(page, n % pdf.PARAGRAPHS_PER_PAGE, 0).split()
        out.append({"id": f"phrase-{n}", "kind": "phrase", "page": page,
                    "text": " ".join(words[2:5])})  # fmt: skip
    for n in range(PER_KIND):
        page = _page(n + 2 * PER_KIND)
        cell = pdf.cell_text(page, n % pdf.TABLE_ROWS, (n * 5) % pdf.TABLE_COLS)
        out.append({"id": f"cell-{n}", "kind": "cell", "page": page, "text": cell})
    for n in range(PER_KIND):
        page = _page(n + 3 * PER_KIND)
        first = pdf.body_text(page, 0, 1).split()[-1]
        last = pdf.body_text(page, pdf.PARAGRAPHS_PER_PAGE - 1, 2).split()[0]
        out.append({"id": f"words-{n}", "kind": "words", "page": page, "text": f"{first} {last}"})
    for n, text in enumerate(ABSENT):
        out.append({"id": f"absent-{n}", "kind": "absent", "page": None, "text": text})
    return out


def render() -> bytes:
    """The file: a schema line, then one query a line, LF, sorted keys."""
    lines = [json.dumps({"schema": SCHEMA, "max_page": MAX_PAGE}, sort_keys=True)]
    lines += [json.dumps(query, sort_keys=True) for query in queries()]
    return ("\n".join(lines) + "\n").encode("utf-8")


def main(argv: list[str] | None = None) -> int:
    """0 the committed file is this script's output (or was written), 1 it differs."""
    parser = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    parser.add_argument("--write", action="store_true")
    args = parser.parse_args(argv)
    data = render()
    if args.write:
        OUT.parent.mkdir(parents=True, exist_ok=True)
        OUT.write_bytes(data)
        sys.stdout.write(f"wrote {OUT.relative_to(HERE.parent.parent).as_posix()}\n")
        return 0
    if not OUT.is_file() or OUT.read_bytes() != data:
        sys.stdout.write(f"MISMATCH  {OUT.name} is not this script's output; run with --write\n")
        return 1
    sys.stdout.write(f"ok        {OUT.name}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
