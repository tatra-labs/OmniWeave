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

## Rulings (the ledger's D775)

8. **`record()` is `brief_digest`'s preimage, and `from_record()` reads it back.** A compile
   retains the canonical bytes of `record()` in CAS, where their digest is `brief_digest` itself,
   as the IL bundle's manifest is `il_digest`'s (D752). `from_record()` is closed at every level.
   The record keeps every value and loses the file's order, which nothing reads: the roster is
   numeric (D764) and the digest sorts. `Template.units` of `None` and of `()` share one record,
   as they share one digest, and read back as `None`, meaning every unit.

## Rulings (the ledger's D776)

9. **`render_brief()` writes a Brief back as `brief/1` text**, in 09's section order with
   `## template` last. `parse_brief()` reads it back as the same Brief when it is given the
   Brief's own baseline rows. `ow out back` writes it as the restored JobDir's `brief.md`, so the
   file the authoring agent re-reads is the Brief the artefact was compiled against.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any, Final, Literal, Never

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
    "render_brief",
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

    def record(self) -> dict[str, Any]:
        """Ruling 8: the object `digest()` hashes, `brief_digest`'s preimage (D775)."""
        return {
            "sections": {name: dict(rows) for name, rows in self.sections.items()},
            "forbidden": [[p.tier, p.text] for p in self.forbidden],
            "template": None
            if self.template is None
            else {"ref": self.template.ref, "units": list(self.template.units or ())},
        }

    def digest(self) -> str:
        """Ruling 7: `brief_digest`."""
        return "sha256:" + sha256_canonical(self.record())

    @classmethod
    def from_record(cls, raw: object) -> Brief:
        """Ruling 8: `record()` read back, closed at every level; `ValueError` otherwise."""
        top = _closed(raw, "brief", frozenset({"sections", "forbidden", "template"}))
        sections = top["sections"]
        if not isinstance(sections, dict) or not all(
            isinstance(name, str)
            and isinstance(rows, dict)
            and all(isinstance(k, str) and isinstance(v, str) for k, v in rows.items())
            for name, rows in sections.items()
        ):
            raise ValueError("brief.sections is not an object of string-to-string objects")
        forbidden = top["forbidden"]
        if not isinstance(forbidden, list) or not all(
            isinstance(row, list)
            and len(row) == 2  # noqa: PLR2004 -- a [tier, text] pair
            and row[0] in {"baseline", "user"}
            and isinstance(row[1], str)
            for row in forbidden
        ):
            raise ValueError("brief.forbidden is not a list of [baseline|user, text] pairs")
        raw_template = top["template"]
        template = None
        if raw_template is not None:
            row = _closed(raw_template, "brief.template", frozenset({"ref", "units"}))
            units = row["units"]
            if not isinstance(row["ref"], str) or not (
                isinstance(units, list) and all(isinstance(u, str) for u in units)
            ):
                raise ValueError("brief.template is not a ref and a list of unit ids")
            template = Template(ref=row["ref"], units=tuple(units) or None)
        return cls(
            sections={name: dict(rows) for name, rows in sections.items()},
            forbidden=tuple(Prohibition(text=text, tier=tier) for tier, text in forbidden),
            template=template,
        )


def _closed(raw: object, where: str, keys: frozenset[str]) -> dict[str, Any]:
    if not isinstance(raw, dict) or frozenset(raw) != keys:
        got = sorted(raw) if isinstance(raw, dict) else type(raw).__name__
        raise ValueError(f"{where} has {got}, not {sorted(keys)}")
    return raw


def render_brief(brief: Brief) -> str:
    """Ruling 9: `brief/1` text that `parse_brief()` reads back as `brief` (D776)."""
    lines = [BRIEF_SCHEMA]
    for name in SECTIONS:
        lines.append(f"## {name}")
        if name == "forbidden":
            lines += [f"- {p.text}{_USER if p.tier == 'user' else ''}" for p in brief.forbidden]
            continue
        lines += [f"- {key}: {value}".rstrip() for key, value in brief.sections[name].items()]
    if brief.template is not None:
        lines += ["## template", f"- ref: {brief.template.ref}"]
        if brief.template.units:
            lines.append(f"- units: {', '.join(brief.template.units)}")
    return "\n".join(lines) + "\n"


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
