"""`derive.anchor.native`'s algorithm: what a document declares about itself. **D670.**

Pure: no I/O, no clock, no store. 06 section 3.3 is the specification -- *"the highest-precision
Pass in the ladder and the cheapest, because it reads structure the format already carries"* -- and
its table lists, per format, which structures carry which `akind`. A Pass reads the store, not the
format, so this module reads the three places a parse driver leaves that structure:

1. **`anchor` marks.** A parse driver records a bookmark (`w:bookmarkStart`, `text:bookmark`, an
   HTML `id=`) and a heading's own id as a zero-width `anchor` mark whose value names it and its
   `akind` (`omniweave_office.blocks._anchor_mark`). Each is an anchor, as declared.
2. **Heading numbering.** 06:1017's "heading numbering" for DOCX/ODT and "ATX heading" for
   Markdown: a `heading` or `title` whose text opens with a section number (`4.2 Indemnity`,
   `1. Definitions`, `Article 7`, `Clause 3.1`) defines that number as a `section` -- `Clause 3.1`
   included, because `derive.xref.pattern`'s `section_ref` reads `clause 3.1` as a `section`
   reference and the two sides join on `akind` by equality. Arabic numbers stand alone; a Roman
   numeral needs its word (`Article IV`), because `I Introduction` and `C Corp` are not.
3. **Labels.** A `caption`, `heading` or `title` that opens with a label word and a number defines
   it: `Figure 3`/`Fig. 3` a `figure`, `Table 2`/`Tab. 2` a `table`, `Exhibit C`/`Schedule 1`/
   `Appendix B`/`Annex II` an `exhibit`, `Equation 4`/`Eq. 4` an `equation` -- 06:1017's
   `SEQ Figure`/`SEQ Table` fields and `<figcaption>`, read off the text they leave. The name forms
   are `derive.xref.pattern`'s capture groups (D669), so the two sides normalise to one `name_norm`.

**Every anchor is `scope = "document"`** (06:1029-1032): a slide title, a figure label, a section
number are document-scoped. A `citekey` or an `identifier` would be corpus-scoped, and this Pass
mints neither: no shipped parse driver records a BibTeX sidecar or a defined identifier.

**What this Pass does not read, and why:** a footnote's label (footnote bodies are containers, no
text, so no Segment holds them; `note_ref` already resolves through L2's `rel`), a list item's
printed marker (`1.` restarts in every list, so it names nothing a reference could), and the PDF
outline, slide names and sheet names (no shipped parse driver records them as marks yet).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import TYPE_CHECKING, Final

from omniweave_graph.vocab import AKINDS

if TYPE_CHECKING:
    from collections.abc import Iterator, Sequence

    from omniweave_graph.view import Member

__all__ = ["Anchor", "find"]

_HEADINGS: Final = frozenset({"heading", "title"})
_LABELLED: Final = frozenset({"heading", "title", "caption"})
_MAX_SURFACE: Final = 200
"""`EntityDraft.title`'s ceiling, used for the displayed surface too: a heading can be a page."""

_NUMBERED: Final = re.compile(
    r"\s*(?:(?P<word>[Aa]rticle|ARTICLE|[Ss]ection|SECTION|[Cc]lause|CLAUSE|[Pp]art|PART"
    r"|[Cc]hapter|CHAPTER)\s+(?P<worded>[0-9]+(?:\.[0-9]+)*|[IVXLC]+)"
    r"|(?P<bare>[0-9]{1,3}(?:\.[0-9]{1,3})*))"
    r"[.):]?(?=\s+\S|\s*$)"
)
"""A bare number is at most three digits a component, so `2020 Annual Report` defines no section
`2020`; a worded one (`Article 2020`) is taken as written."""
_LABEL: Final = re.compile(
    r"\s*(?P<word>(?i:Figure|Fig\.|Table|Tab\.|Exhibit|Schedule|Appendix|Annex|Equation|Eq\.))"
    r"\s+(?P<name>[0-9]+[a-z]?(?:\.[0-9]+)?|[A-Z]{1,3})\b"
)
"""The word is matched in any case (`SCHEDULE 1`); the name is not, so `Table of Contents` names no
table -- `of` is not an exhibit letter."""
_LABEL_AKIND: Final = {
    "figure": "figure",
    "fig.": "figure",
    "table": "table",
    "tab.": "table",
    "exhibit": "exhibit",
    "schedule": "exhibit",
    "appendix": "exhibit",
    "annex": "exhibit",
    "equation": "equation",
    "eq.": "equation",
}


@dataclass(frozen=True, slots=True)
class Anchor:
    cite: str
    span: tuple[int, int]
    """In `block.text`, half-open. A mark's span may be empty: `a == b` is a zero-width anchor."""
    name: str
    akind: str
    surface: str
    rule: str


def find(members: Sequence[Member]) -> tuple[Anchor, ...]:
    """Every declared anchor in one Segment, in reading order."""
    out: list[Anchor] = []
    for member in members:
        found = [*_marks(member), *_numbered(member), *_labelled(member)]
        out += sorted(found, key=lambda a: (a.span, a.rule))
    return tuple(out)


def _surface(text: str) -> str:
    one = " ".join(text.split())
    return one[:_MAX_SURFACE]


def _marks(member: Member) -> Iterator[Anchor]:
    text = member.text or ""
    for mark in member.marks:
        if mark.kind != "anchor" or not isinstance(mark.value, dict):
            continue
        name, akind = mark.value.get("name"), mark.value.get("akind")
        if not isinstance(name, str) or not name.strip() or akind not in AKINDS:
            continue
        if mark.b > len(text):
            continue
        yield Anchor(
            cite=member.cite,
            span=(mark.a, mark.b),
            name=name,
            akind=str(akind),
            surface=_surface(name),
            rule="mark",
        )


def _numbered(member: Member) -> Iterator[Anchor]:
    if member.kind not in _HEADINGS or member.text is None:
        return
    match = _NUMBERED.match(member.text)
    if match is None:
        return
    group = "worded" if match.group("worded") is not None else "bare"
    yield Anchor(
        cite=member.cite,
        span=match.span(group),
        name=match.group(group),
        akind="section",
        surface=_surface(member.text),
        rule="numbered",
    )


def _labelled(member: Member) -> Iterator[Anchor]:
    if member.kind not in _LABELLED or member.text is None:
        return
    match = _LABEL.match(member.text)
    if match is None:
        return
    yield Anchor(
        cite=member.cite,
        span=match.span("name"),
        name=match.group("name"),
        akind=_LABEL_AKIND[match.group("word").casefold()],
        surface=_surface(member.text),
        rule="label",
    )
