"""`derive.xref.native`'s algorithm: the references a document's own links make. **D671.**

Pure: no I/O, no clock, no store. 06 section 3.4 names the structures -- `w:instrText REF/PAGEREF`,
`a:hlinkClick`, ODF `text:reference-ref`, PDF `/Link` + `GoTo`, HTML `href="#..."` -- and, as
`derive.anchor.native` does (D670), this Pass reads what a parse driver left of them in the store:
a `link` mark whose value is `{"target": ..., "kind": "external" | "internal" | "anchor"}`
(03:360, `omniweave_office.blocks`).

## The readings this module takes where the plan is silent

1. **Only an `anchor` link is a reference occurrence.** Its target is a position inside this
   document, so it resolves against this document's anchors. An `external` link names no anchor.
   An `internal` one names another document by a relative path, which no anchor row can hold
   (`anchor` is per document, by name), so it is recorded nowhere until a corpus-scoped link
   target exists.
2. **The name is the target with one leading `#` removed**, exactly as written otherwise --
   `normalize_key` on both sides does the rest.
3. **The `akind` is the one the document declared for that name.** A link knows its target's name
   and not its kind, and the views join on `akind` by equality. A unit is a whole document's
   Segments (D668), so every `anchor` mark of the document is in hand: a target named by one takes
   that mark's `akind` (`section` for a heading id, `bookmark` for a bookmark). A target the
   document names nowhere is a `bookmark` -- the kind an `href="#..."` or a `REF` field points at --
   and is honestly unresolved.
4. **The occurrence is the link's own span**, the linked text, whose surface is that text; an empty
   link (`a == b`) takes the target as its surface.
5. **At most `MAX_REF_SITES_PER_BLOCK = 32` a block**, as `derive.xref.pattern`'s, the rest a
   `Diag(OW_REFSITE_TRUNCATED)`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Final

from omniweave_graph.vocab import AKINDS

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping, Sequence

    from omniweave_graph.view import Member

__all__ = ["MAX_REF_SITES_PER_BLOCK", "Found", "Link", "Notice", "declared_kinds", "find"]

MAX_REF_SITES_PER_BLOCK: Final = 32
_TRUNCATED: Final = "OW_REFSITE_TRUNCATED"
_DEFAULT_AKIND: Final = "bookmark"


@dataclass(frozen=True, slots=True)
class Link:
    cite: str
    span: tuple[int, int]
    name: str
    akind: str
    surface: str


@dataclass(frozen=True, slots=True)
class Notice:
    code: str
    message: str
    cite: str
    detail: dict[str, object] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class Found:
    links: tuple[Link, ...]
    notices: tuple[Notice, ...]


def declared_kinds(members: Iterable[Member]) -> dict[str, str]:
    """Reading 3: every `anchor` mark's name to its declared `akind`, first declaration winning."""
    out: dict[str, str] = {}
    for member in members:
        for mark in member.marks:
            if mark.kind != "anchor" or not isinstance(mark.value, dict):
                continue
            name, akind = mark.value.get("name"), mark.value.get("akind")
            if isinstance(name, str) and name and akind in AKINDS:
                out.setdefault(name, str(akind))
    return out


def find(members: Sequence[Member], kinds: Mapping[str, str]) -> Found:
    """Every in-document link in one Segment, in reading order, typed by `kinds`."""
    links: list[Link] = []
    notices: list[Notice] = []
    for member in members:
        if member.text is None:
            continue
        found = sorted(_links(member, kinds), key=lambda link: link.span)
        if len(found) > MAX_REF_SITES_PER_BLOCK:
            notices.append(
                Notice(
                    code=_TRUNCATED,
                    message=(
                        f"{len(found)} links in one block; the first "
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
        links += found[:MAX_REF_SITES_PER_BLOCK]
    return Found(links=tuple(links), notices=tuple(notices))


def _links(member: Member, kinds: Mapping[str, str]) -> list[Link]:
    text = member.text or ""
    out: list[Link] = []
    for mark in member.marks:
        if mark.kind != "link" or not isinstance(mark.value, dict):
            continue
        if mark.value.get("kind") != "anchor" or mark.b > len(text):
            continue
        target = mark.value.get("target")
        if not isinstance(target, str):
            continue
        name = target.removeprefix("#")
        if not name.strip():
            continue
        out.append(
            Link(
                cite=member.cite,
                span=(mark.a, mark.b),
                name=name,
                akind=kinds.get(name, _DEFAULT_AKIND),
                surface=text[mark.a : mark.b] or target,
            )
        )
    return out
