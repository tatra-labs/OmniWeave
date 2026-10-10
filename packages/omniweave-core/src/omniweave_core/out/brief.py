"""The `Brief`: a locked spec, two productions and nothing else, and `parse_brief()`. **D740.**

09-generation.md section 13.2. The answers to the scoping questions are written to a file, so a
fresh session re-reads them rather than re-deriving or contradicting the confirmed direction. The
grammar is ppt-master's `spec_lock.md`, adopted whole: a schema-version comment on line 1, then
only `## section` headings and `- key: value` rows, with `## forbidden` holding literal rules.

## Rulings (the ledger's D740)

1. **The sections are a closed set.** The eight 09 prints are required, `## template` is optional
   (section 4.1), and any other heading is refused like any line outside the two productions. A
   blank line is layout. An optional `# Brief` title may follow line 1, as 09's own example has.
2. **A value is the rest of the line, and there are no inline comments.** 09's example annotates
   `primary_language` with a trailing `# canonical BCP-47 ...`. A `core_message` may hold a `#`, so
   stripping one would edit the user's words. The annotation is the plan's, not the grammar's.
3. **The keys a framework rule reads are required; the prose keys are the author's.** `canvas` needs
   `format` and `unit`, `communication` needs `primary_language`, `density` needs `per_unit` (09's
   four brackets) and `motion` needs `level` (its three). A repeated key or section is refused.
4. **`primary_language` is canonical BCP-47**: a 2-3 letter language, then an optional title-case
   script, then an optional upper-case region or 3-digit area, in that casing. `und` is refused, and
   so is Chinese without a script (`zh`, `zh-CN`), because the script is the decision.
5. **The baseline tier is generated as one row per forbidden construct, `"<id>: <msg>"`.** 09 says
   an untagged row is checkable *"because the baseline tier is generated from the ConstructTable's
   `forbidden` rows"*. Its example row (`- <script>, <style>, class=, ...`) is prose, which no table
   can generate. `baseline_rows(table)` is the generator, and an untagged row must be one of its
   lines exactly.
6. **A `(user)` row keeps its text verbatim**, the tag stripped and nothing else.
7. **`digest()` is over the parsed Brief**, `sha256:` and `sha256_canonical` of its sections and
   rules. A blank line or a CRLF checkout does not move `brief_digest`, one of the six purity
   inputs, and every value does.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Final, Literal, Never

from omniweave_core.canonical import sha256_canonical
from omniweave_core.errors import TargetError
from omniweave_core.out.constructs import ConstructTable, Disposition

__all__ = [
    "BRIEF_SCHEMA",
    "SECTIONS",
    "Brief",
    "Prohibition",
    "Template",
    "baseline_rows",
    "parse_brief",
]

BRIEF_SCHEMA: Final = "<!-- omniweave-schema: brief/1 -->"
SECTIONS: Final = (
    "canvas",
    "communication",
    "direction",
    "density",
    "motion",
    "typography",
    "rhythm",
    "forbidden",
)
"""Ruling 1: the eight required sections, in 09's order."""
_OPTIONAL: Final = ("template",)
_REQUIRED_KEYS: Final[dict[str, tuple[str, ...]]] = {
    "canvas": ("format", "unit"),
    "communication": ("primary_language",),
    "density": ("per_unit",),
    "motion": ("level",),
}
_CLOSED: Final[dict[tuple[str, str], frozenset[str]]] = {
    ("density", "per_unit"): frozenset({"minimal", "light", "standard", "dense"}),
    ("motion", "level"): frozenset({"static", "subtle", "rich"}),
}
_HEADING: Final = re.compile(r"## ([a-z_]+)")
_ROW: Final = re.compile(r"- ([a-z_][a-z0-9_]*|u\d{2,}):[ \t]*(.*)")
_ITEM: Final = re.compile(r"- (.+)")
_USER: Final = " (user)"
_BCP47: Final = re.compile(
    r"(?P<lang>[a-z]{2,3})(?:-(?P<script>[A-Z][a-z]{3}))?(?:-(?P<region>[A-Z]{2}|\d{3}))?"
)
_SLOT: Final = re.compile(r"asset-slot:[0-9a-f]{64}")
_UNIT: Final = re.compile(r"u\d{2,}")
_FIX: Final = "ow explain OW-T-008"
_TITLE_LINE: Final = 2
"""Ruling 1: the optional `# Brief` title sits on the line after the schema comment."""


@dataclass(frozen=True, slots=True)
class Prohibition:
    """One `## forbidden` row (09 section 13.2's three tiers, less the template's)."""

    text: str
    tier: Literal["baseline", "user"]


@dataclass(frozen=True, slots=True)
class Template:
    """`## template`: the frozen template and the units derived from it (09 section 4.1)."""

    ref: str
    units: tuple[str, ...] | None
    """`None` when the row is omitted, which means all units."""


@dataclass(frozen=True, slots=True)
class Brief:
    """A parsed `brief/1`. The role that consumes it cannot write it, so it is frozen."""

    sections: Mapping[str, Mapping[str, str]]
    """Every key-value section in file order, `## forbidden` excepted."""
    forbidden: tuple[Prohibition, ...]
    template: Template | None

    def value(self, section: str, key: str) -> str | None:
        return self.sections.get(section, {}).get(key)

    def rhythm(self) -> dict[str, dict[str, str]]:
        """`## rhythm` as unit -> its inline map: `- u01: { anchor: cover, dense: false }`."""
        return {unit: _inline(value) for unit, value in self.sections.get("rhythm", {}).items()}

    def anchor(self, unit: str) -> str:
        """`OutUnit.anchor`: the unit's rhythm anchor, or `""` when the Brief declared none."""
        return self.rhythm().get(unit, {}).get("anchor", "")

    def digest(self) -> str:
        """Ruling 7: `brief_digest`."""
        return "sha256:" + sha256_canonical(
            {
                "sections": {name: dict(rows) for name, rows in self.sections.items()},
                "forbidden": [[p.tier, p.text] for p in self.forbidden],
                "template": None
                if self.template is None
                else {"ref": self.template.ref, "units": list(self.template.units or ())},
            }
        )


def baseline_rows(table: ConstructTable) -> tuple[str, ...]:
    """Ruling 5: the technical baseline tier, one line per forbidden construct."""
    return tuple(
        f"{row.id}: {row.msg}" for row in table.rows if row.disposition is Disposition.FORBIDDEN
    )


def parse_brief(text: str, *, baseline: Iterable[str]) -> Brief:
    """Parse and assert one Brief. `baseline` is `baseline_rows()` of the target's table."""
    lines = text.split("\n")  # each line is rstrip()ped below, which takes a CRLF's \r too
    if not lines or lines[0].strip() != BRIEF_SCHEMA:
        _fail(1, f"line 1 must be {BRIEF_SCHEMA!r}")
    allowed_baseline = frozenset(baseline)
    sections: dict[str, dict[str, str]] = {}
    forbidden: list[Prohibition] = []
    current: str | None = None
    for number, raw in enumerate(lines[1:], start=2):
        line = raw.rstrip()
        if not line or (number == _TITLE_LINE and line == "# Brief"):
            continue
        if (heading := _HEADING.fullmatch(line)) is not None:
            current = heading.group(1)
            if current not in SECTIONS and current not in _OPTIONAL:
                _fail(number, f"## {current} is not a Brief section")
            if current in sections:
                _fail(number, f"## {current} appears twice")
            sections[current] = {}
            continue
        if current is None:
            _fail(number, "a row before the first ## section")
        if current == "forbidden":
            item = _ITEM.fullmatch(line)
            if item is None:
                _fail(number, "a ## forbidden row is `- <rule>`")
            forbidden.append(_prohibition(item.group(1), allowed_baseline, number))
            continue
        row = _ROW.fullmatch(line)
        if row is None:
            _fail(number, "not a `- key: value` row")
        key, value = row.group(1), row.group(2).strip()
        if key in sections[current]:
            _fail(number, f"{key} appears twice in ## {current}")
        sections[current][key] = value
    missing = [name for name in SECTIONS if name not in sections]
    if missing:
        _fail(len(lines), f"missing section(s): {', '.join('## ' + m for m in missing)}")
    _assert_keys(sections)
    template = _template(sections.pop("template", None))
    sections.pop("forbidden")
    return Brief(sections=sections, forbidden=tuple(forbidden), template=template)


def _prohibition(text: str, baseline: frozenset[str], number: int) -> Prohibition:
    if text.endswith(_USER):
        return Prohibition(text.removesuffix(_USER), "user")
    if text not in baseline:
        _fail(
            number,
            f"untagged prohibition {text!r} is not in the ConstructTable's baseline; "
            "a user's own rule ends ' (user)'",
        )
    return Prohibition(text, "baseline")


def _assert_keys(sections: Mapping[str, Mapping[str, str]]) -> None:
    for section, keys in _REQUIRED_KEYS.items():
        for key in keys:
            if not sections[section].get(key):
                _fail(0, f"## {section} needs `- {key}: ...`")
    for (section, key), allowed in _CLOSED.items():
        if sections[section][key] not in allowed:
            _fail(
                0, f"## {section} {key} is one of {sorted(allowed)}, not {sections[section][key]!r}"
            )
    _language(sections["communication"]["primary_language"])
    for unit in sections["rhythm"]:
        if _UNIT.fullmatch(unit) is None:
            _fail(0, f"## rhythm row {unit!r} is not a unit id")


def _language(tag: str) -> None:
    """Ruling 4."""
    m = _BCP47.fullmatch(tag)
    if m is None:
        _fail(0, f"primary_language {tag!r} is not canonical BCP-47 (en-GB, zh-Hans-CN)")
    if m["lang"] == "und":
        _fail(0, "primary_language `und` says nothing; name the language")
    if m["lang"] == "zh" and m["script"] is None:
        _fail(0, f"primary_language {tag!r}: Chinese needs its script, zh-Hans or zh-Hant")


def _template(rows: Mapping[str, str] | None) -> Template | None:
    if rows is None:
        return None
    unknown = sorted(set(rows) - {"ref", "units"})
    if unknown:
        _fail(0, f"## template takes ref and units, not {unknown}")
    ref = rows.get("ref", "")
    if _SLOT.fullmatch(ref) is None:
        _fail(0, f"## template ref {ref!r} is not asset-slot:<sha256>")
    units = None
    if "units" in rows:
        units = tuple(u.strip() for u in rows["units"].split(","))
        if not units or not all(_UNIT.fullmatch(u) for u in units):
            _fail(0, f"## template units {rows['units']!r} is not a list of unit ids")
    return Template(ref, units)


def _inline(value: str) -> dict[str, str]:
    """`{ anchor: cover, dense: false }` to a mapping; anything else is no map at all."""
    body = value.strip()
    if not (body.startswith("{") and body.endswith("}")):
        return {}
    out: dict[str, str] = {}
    for part in body[1:-1].split(","):
        key, colon, rest = part.partition(":")
        if colon:
            out[key.strip()] = rest.strip()
    return out


def _fail(line: int, msg: str) -> Never:
    where = f"brief.md:{line}: " if line else "brief.md: "
    raise TargetError(where + msg, symbol="OW_TARGET_BRIEF_INVALID", fix=_FIX)
