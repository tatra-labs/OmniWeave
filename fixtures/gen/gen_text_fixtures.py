#!/usr/bin/env python3
"""Generate `parse.text.builtin`'s conformance corpus: one case per format, and the refusals.

Every file is a literal in this script, for `gen_office_fixtures.py`'s three reasons: the script is
the provenance record, the bytes are a function of this file alone so `EXPECTED.sha256` is a real
check, and each file is a CASE -- the construct the reader for its format has to get right.

Usage:

    uv run python fixtures/gen/gen_text_fixtures.py
    uv run python fixtures/gen/gen_text_fixtures.py --out <dir>   # default: the office package

Specified in 04-driver-system.md section 10.1; 13-quality.md section 4 (fixture tiers and
provenance).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OUT = ROOT / "packages" / "omniweave-office" / "fixtures" / "text"

GUIDE_MD = """---
title: Onboarding guide
owner: platform
---

Onboarding guide
================

Welcome to the **platform** team. Read this first.

## Setup

1. Install the toolchain.
2. Clone the repository:
   it lives on the internal host.
3. Run the tests.

- Editors
  - VS Code
  - JetBrains
- Terminals

> The on-call rota starts in your second week.
> Ask your buddy for the pager.

```python
def hello() -> str:
    return "hi"
```

| service | owner | tier |
|---------|-------|------|
| billing | Ana   | 1    |
| search  | Bo    | 2    |

***

### Escalation

Page the secondary if the primary does not answer in 15 minutes.
"""

NOTES_TXT = """Meeting notes, 2026-03-02.

The launch moves to April 14 because the audit is not finished.
Finance signs off on the budget next week.

Action: Dana writes the release notes.
"""

PAGE_HTML = """<!DOCTYPE html>
<html>
<head><title>Status page</title><style>p { color: red; }</style></head>
<body>
<h1>Service status</h1>
<p>All systems are operating normally &amp; on schedule.</p>
<script>console.log("not content");</script>
<h2>Regions</h2>
<ul>
  <li>Europe: <b>green</b></li>
  <li>Asia: amber</li>
</ul>
<table>
  <tr><th>Region</th><th colspan="2">Latency</th></tr>
  <tr><td rowspan="2">Europe</td><td>p50</td><td>12 ms</td></tr>
  <tr><td>p99</td><td>80 ms</td></tr>
</table>
<blockquote><p>Uptime is a feature.</p></blockquote>
<pre>curl https://status.example/api
</pre>
<hr>
<p>Last updated at 09:00 UTC.</p>
</body>
</html>
"""

PAGE_XHTML = """<?xml version="1.0" encoding="UTF-8"?>
<html xmlns="http://www.w3.org/1999/xhtml">
<head><title>Policy</title></head>
<body>
<h1>Travel policy</h1>
<p>Economy class for flights under six hours.<br/>Business class above.</p>
<ol start="3"><li>Book through the portal.</li><li>Keep the receipts.</li></ol>
</body>
</html>
"""

CATALOG_XML = """<?xml version="1.0" encoding="UTF-8"?>
<catalog>
  <book id="b1"><title>The Pragmatic Programmer</title><year>1999</year></book>
  <book id="b2"><title>Refactoring</title><year>2018</year></book>
</catalog>
"""

ENTITIES_XML = """<?xml version="1.0"?>
<!DOCTYPE lolz [
  <!ENTITY lol "lol">
  <!ENTITY lol2 "&lol;&lol;&lol;&lol;&lol;&lol;&lol;&lol;&lol;&lol;">
]>
<lolz>&lol2;</lolz>
"""

DATA_JSON = (
    json.dumps(
        {
            "service": "billing",
            "owners": ["Ana", "Bo"],
            "limits": {"rps": 1200, "burst": True},
            "region": None,
        },
        indent=2,
    )
    + "\n"
)

EVENTS_JSONL = "".join(
    json.dumps(record) + "\n"
    for record in (
        {"at": "2026-03-01T09:00:00Z", "event": "deploy", "service": "search"},
        {"at": "2026-03-01T09:05:00Z", "event": "rollback", "service": "search"},
    )
)

NOTEBOOK = (
    json.dumps(
        {
            "nbformat": 4,
            "nbformat_minor": 5,
            "metadata": {"kernelspec": {"name": "python3", "language": "python"}},
            "cells": [
                {
                    "cell_type": "markdown",
                    "metadata": {},
                    "source": ["# Churn analysis\n", "\n", "Monthly churn by plan."],
                },
                {
                    "cell_type": "code",
                    "metadata": {},
                    "execution_count": 1,
                    "source": ["rate = 42 / 1000\n", "print(rate)"],
                    "outputs": [{"output_type": "stream", "name": "stdout", "text": ["0.042\n"]}],
                },
            ],
        },
        indent=1,
    )
    + "\n"
)

ROWS_TSV = "name\tteam\tstart\nAna\tbilling\t2024-01-08\nBo\tsearch\t2025-06-02\n"

LOGO_SVG = """<?xml version="1.0" encoding="UTF-8"?>
<svg xmlns="http://www.w3.org/2000/svg" width="120" height="40">
  <title>Acme logo</title>
  <desc>The Acme wordmark on a blue bar</desc>
  <rect width="120" height="40" fill="#1155cc"/>
  <text x="10" y="26">Acme <tspan font-weight="bold">Corp</tspan></text>
</svg>
"""

FIXTURES: dict[str, tuple[bytes, str | None, str]] = {
    "guide.md": (
        GUIDE_MD.encode(),
        "text/markdown",
        "Markdown: front matter, setext and ATX headings, ordered, bullet and nested lists, a "
        "block quote, fenced code with its language, a pipe table and a thematic break",
    ),
    "notes.txt": (
        NOTES_TXT.encode(),
        "text/plain",
        "plain text: paragraphs split on blank lines, each keeping its line breaks",
    ),
    "latin1.txt": (
        "Café au lait, crème brûlée.\n".encode("latin-1"),
        "text/plain",
        "bytes that are not UTF-8: read as Latin-1, with an OW_TEXT_NOT_UTF8 warning diag",
    ),
    "page.html": (
        PAGE_HTML.encode(),
        "text/html",
        "HTML: headings, an entity, a list, a table with colspan and rowspan, a block quote, pre, "
        "hr; the head, style and script are not content",
    ),
    "page.xhtml": (
        PAGE_XHTML.encode(),
        "application/xhtml+xml",
        "XHTML: self-closing br, and an ordered list that starts at 3",
    ),
    "catalog.xml": (
        CATALOG_XML.encode(),
        "application/xml",
        "XML: the text of each element that has any, in document order",
    ),
    "entities.xml": (
        ENTITIES_XML.encode(),
        "application/xml",
        "XML with a DTD declaring nested entities (billion laughs): defusedxml refuses it, and "
        "parse() refuses with CORRUPT_INPUT without expanding anything",
    ),
    "data.json": (
        DATA_JSON.encode(),
        "application/json",
        "JSON: one `path: value` paragraph per leaf, nested objects and arrays included",
    ),
    "broken.json": (
        b'{"service": "billing", "owners": ["Ana"',
        "application/json",
        "JSON cut short: parse() refuses with CORRUPT_INPUT naming the parser's message",
    ),
    "events.jsonl": (
        EVENTS_JSONL.encode(),
        "application/jsonl",
        "JSON Lines: one paragraph per record, its leaves joined",
    ),
    "analysis.ipynb": (
        NOTEBOOK.encode(),
        "application/x-ipynb+json",
        "a notebook: a markdown cell read as Markdown, a code cell as python code, its stream "
        "output as code with no language",
    ),
    "rows.tsv": (
        ROWS_TSV.encode(),
        "text/tab-separated-values",
        "TSV: one table, the first row its header",
    ),
    "logo.svg": (
        LOGO_SVG.encode(),
        "image/svg+xml",
        "SVG: its title, desc and text elements, the only text an SVG says",
    ),
    "not_a_document.bin": (
        b"\x7fELF\x02\x01\x01\x00" + bytes(32),
        None,
        "an ELF header. sniff() returns (), a legitimate `not mine`, and parse() refuses with "
        "UNSUPPORTED_FORMAT. NO SIDECAR MEDIA TYPE, because nothing routed it",
    ),
}


SIDECAR = """# {name}.meta.toml -- 13-quality.md section 4.4's fixture manifest.
#
# {purpose}
[fixture]
sha256 = "{digest}"
bytes = {size}
{media}provenance = "generated"
spdx = "Apache-2.0"
generator = "fixtures/gen/gen_text_fixtures.py"
# `generated` is 13-quality.md section 4.2's PREFERRED provenance: the generator path and the
# expected output sha256 are above, and it carries no `review_by` because it depends on nothing
# outside this repository.
"""


def sidecar(name: str, data: bytes, media_type: str | None, purpose: str) -> str:
    """One `.meta.toml` per fixture; `media_type` is omitted when nothing routed the file."""
    media = f'media_type = "{media_type}"\n' if media_type else ""
    return SIDECAR.format(
        name=name,
        purpose=purpose,
        digest=hashlib.sha256(data).hexdigest(),
        size=len(data),
        media=media,
    )


def report(line: str) -> None:
    sys.stdout.write(f"{line}\n")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    lines = []
    for name, (data, media_type, purpose) in sorted(FIXTURES.items()):
        (args.out / name).write_bytes(data)
        (args.out / f"{name}.meta.toml").write_text(
            sidecar(name, data, media_type, purpose), encoding="utf-8", newline="\n"
        )
        lines.append(f"{hashlib.sha256(data).hexdigest()}  {name}\n")
        report(f"{name:22s} {len(data):7d} bytes")
    (args.out / "EXPECTED.sha256").write_text("".join(lines), encoding="utf-8", newline="\n")
    report(f"\n{len(lines)} fixtures -> {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
