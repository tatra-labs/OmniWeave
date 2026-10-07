"""`derive.xref.pattern`'s algorithm: members in, reference occurrences out. **D669.**

Pure: no I/O beyond reading this package's own `patterns.toml`, no clock, no store. 06 section 3.4
is the specification: a fixed, versioned regex set over body prose, held as data so a corpus can
tune it, at most `MAX_REF_SITES_PER_BLOCK = 32` occurrences per block, a breach a
`Diag(OW_REFSITE_TRUNCATED)` that counts what it dropped.

## The readings this module takes where the plan is silent

1. **The name is the pattern's first group; the occurrence is the whole match.** `XrefDraft.name`
   is what resolves (`4.2(b)`, `C`, `GL-4471`), and `at` spans the whole match (`Section 4.2(b)`),
   because `ref_site.surface` is *"'section 4.2(b)' as written"* and `ts_a`/`ts_b` locate it.
2. **Two patterns on overlapping text keep the earlier, then the longer, match.** The fixture set is
   asserted non-overlapping in CI, but a corpus is not the fixture set; one occurrence is one
   `ref_site`, never two.
3. **Every text-bearing kind is read except `code`, `formula`, `toc`, `toc_entry`, `page_header`
   and `page_footer`** -- the same set `derive.anchor.defterm` skips (D666 reading 9). A heading is
   read: `See Section 4` is rarely one, but `Schedule 2 -- Fees` is a heading and a reference
   at once.
4. **The occurrences are kept in reading order, and the first 32 of a block are written.**
"""

from __future__ import annotations

import re
import tomllib
from dataclasses import dataclass, field
from functools import cache
from importlib.resources import files
from typing import TYPE_CHECKING, Final

if TYPE_CHECKING:
    from collections.abc import Sequence

    from omniweave_graph.view import Member

__all__ = [
    "MAX_REF_SITES_PER_BLOCK",
    "Found",
    "Notice",
    "Pattern",
    "Ref",
    "find",
    "patterns",
]

MAX_REF_SITES_PER_BLOCK: Final = 32
"""06:1095 and 0003_index.sql: a breach is `Diag(OW_REFSITE_TRUNCATED)` and is counted."""

_TRUNCATED: Final = "OW_REFSITE_TRUNCATED"
_SKIP_KINDS: Final = frozenset(
    {"code", "formula", "toc", "toc_entry", "page_header", "page_footer"}
)
_AKINDS: Final = frozenset(
    {
        "section",
        "clause",
        "figure",
        "table",
        "equation",
        "citekey",
        "identifier",
        "defined_term",
        "footnote",
        "exhibit",
        "slide",
        "sheet",
        "glossary",
        "bookmark",
    }
)
"""`AnchorKind`'s fourteen values, which this package may not import from core;
`tests/unit/test_xref_rules.py` holds the two equal."""
_MIN_FIXTURES: Final = 3


@dataclass(frozen=True, slots=True)
class Pattern:
    name: str
    akind: str
    scope: str
    expression: re.Pattern[str]
    yes: tuple[str, ...]
    no: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class Ref:
    """One reference occurrence: what `XrefDraft` carries."""

    cite: str
    span: tuple[int, int]
    """The whole match in `block.text`, half-open, in characters."""
    name: str
    akind: str
    surface: str
    pattern: str


@dataclass(frozen=True, slots=True)
class Notice:
    code: str
    message: str
    cite: str
    detail: dict[str, object] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class Found:
    refs: tuple[Ref, ...]
    notices: tuple[Notice, ...]


@cache
def patterns() -> tuple[Pattern, ...]:
    """`patterns.toml`, compiled and checked. A malformed set is a packaging bug and raises."""
    raw = tomllib.loads(
        files("omniweave_graph.xref").joinpath("patterns.toml").read_text(encoding="utf-8")
    )
    out: list[Pattern] = []
    for table in raw.get("pattern", []):
        expression = re.compile(table["re"])
        pattern = Pattern(
            name=table["name"],
            akind=table["akind"],
            scope=table["scope"],
            expression=expression,
            yes=tuple(table["yes"]),
            no=tuple(table["no"]),
        )
        if pattern.akind not in _AKINDS or pattern.scope not in {"document", "corpus"}:
            raise ValueError(f"pattern {pattern.name}: akind or scope is out of vocabulary")
        if expression.groups < 1:
            raise ValueError(f"pattern {pattern.name}: the name is the first group; it has none")
        if len(pattern.yes) < _MIN_FIXTURES or len(pattern.no) < _MIN_FIXTURES:
            raise ValueError(f"pattern {pattern.name}: three yes and three no fixtures at least")
        out.append(pattern)
    names = [p.name for p in out]
    if len(set(names)) != len(names):
        raise ValueError("two patterns share a name")
    return tuple(out)


def find(members: Sequence[Member]) -> Found:
    """Every reference occurrence in one Segment, in reading order, and the Diags owed."""
    refs: list[Ref] = []
    notices: list[Notice] = []
    for member in members:
        if member.text is None or member.kind in _SKIP_KINDS:
            continue
        found = _block(member.cite, member.text)
        if len(found) > MAX_REF_SITES_PER_BLOCK:
            notices.append(
                Notice(
                    code=_TRUNCATED,
                    message=(
                        f"{len(found)} reference occurrences in one block; the first "
                        f"{MAX_REF_SITES_PER_BLOCK} are kept"
                    ),
                    cite=member.cite,
                    detail={
                        "limit": "MAX_REF_SITES_PER_BLOCK",
                        "value": MAX_REF_SITES_PER_BLOCK,
                        "found": len(found),
                    },
                )
            )
        refs += found[:MAX_REF_SITES_PER_BLOCK]
    return Found(refs=tuple(refs), notices=tuple(notices))


def _block(cite: str, text: str) -> list[Ref]:
    """Reading 2: every pattern's matches, then the earlier and longer of any two that overlap."""
    hits: list[Ref] = []
    for pattern in patterns():
        for match in pattern.expression.finditer(text):
            name = match.group(1)
            if not name:
                continue
            hits.append(
                Ref(
                    cite=cite,
                    span=match.span(),
                    name=name,
                    akind=pattern.akind,
                    surface=match.group(0),
                    pattern=pattern.name,
                )
            )
    hits.sort(key=lambda r: (r.span[0], -(r.span[1] - r.span[0]), r.pattern))
    kept: list[Ref] = []
    end = -1
    for ref in hits:
        if ref.span[0] >= end:
            kept.append(ref)
            end = ref.span[1]
    return kept
