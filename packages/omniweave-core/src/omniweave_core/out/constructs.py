"""`constructs.toml`, the IL contract as data: `ConstructTable.load()` and its assertions. **D739.**

09-generation.md sections 3.3 to 3.6; charter OUT1 and OUT20. A Target's ConstructTable is one row
per allowed construct, read by the validator, the compiler, the doc generator and the kit. It is
data, so every way it could lie is refused when it loads: a missing or forbidden key for the row's
disposition, a normalize row pointing at anything but a native row, a normalizer the target does
not ship, a selector that does not parse, an unknown key.

## Rulings (the ledger's D739)

1. **An unknown key is a load error, at the top and in a row.** A misspelt `forbiden_when` would
   otherwise load as a native row with no condition: the silently disabled prohibition 09 section
   3.4 assertion 3 calls the worst failure in the file.
2. **`severity` is a normalize row's key alone.** Section 3.3 fixes every other disposition's
   severity (native none, forbidden error, bake by availability), so a `severity` on any other row
   could only contradict it.
3. **`msg` is optional except on a forbidden row**, where it is required. The charter's `attr.id`
   carries one as a native row with `forbidden_when`, and a conditional prohibition needs its
   message as much as an unconditional one.
4. **The mandatory constructs are recognised by the attribute their selector names**:
   `data-ow-cite`, `data-ow-el` and `data-ow-manual`, as an attribute selector or an element
   qualifier. `ow:unit` is the unit root, which each carrier spells its own way (the `svg` root,
   the reference target's `html|section`), so the table cannot show it and order 10's structural
   rule checks it instead.
5. **`ignore` is selectors in section 3.1's grammar**, as 09 section 3.4 prints it. The charter's
   `svg:desc` and the API sketch's `html:head` use a colon the grammar refuses, and load as an
   error rather than as nothing ignored.
6. **`since` is checked as a version; its monotonicity is not.** Section 3.4 assertion 4 says it
   never decreases across version bumps, which needs the previous table, and section 3.6 says that
   table is not on disk. The kit holds a shipped table to its own history.
7. **The digest is `sha256_canonical` over the table as loaded from TOML**, prefixed `sha256:`,
   so whitespace and comments do not move it and every value does.
"""

from __future__ import annotations

import re
import tomllib
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any, Final, Never

from omniweave_core.canonical import sha256_canonical
from omniweave_core.errors import TargetError
from omniweave_core.out.carrier import CarrierDoc, Selector, parse_selector

__all__ = [
    "CONSTRUCTS_SCHEMA",
    "MANDATORY_ATTRIBUTES",
    "Bake",
    "Construct",
    "ConstructTable",
    "Disposition",
    "RoundTrip",
]

CONSTRUCTS_SCHEMA: Final = "omniweave.out-constructs/1"
MANDATORY_ATTRIBUTES: Final = ("data-ow-cite", "data-ow-el", "data-ow-manual")
"""Ruling 4: `ow:cite`, the `data-ow-el` attribute and `ow:manual`, by the attribute they name."""

_CARRIERS: Final = frozenset({"svg", "html"})
_TOP_KEYS: Final = frozenset(
    {"schema", "carrier", "il", "version", "unknown_construct", "ignore", "construct"}
)
_ROW_KEYS: Final = frozenset(
    {
        "id", "selector", "disposition", "round_trip", "canonical", "maps_to", "normalizes_to",
        "normalizer", "bake", "forbidden_when", "msg", "severity", "code", "since", "visible",
    }
)  # fmt: skip
_BAKE_KEYS: Final = frozenset({"renderer", "dpi", "role"})
_SYMBOL: Final = re.compile(r"OW_[A-Z0-9_]+")
_VERSION: Final = re.compile(r"\d+\.\d+\.\d+")
_FIX: Final = "ow explain OW-T-007"
_TABLE_FIX: Final = "ow explain OW-T-009"


class Disposition(StrEnum):
    """09 section 3.3's four states."""

    NATIVE = "native"
    NORMALIZE = "normalize"
    BAKE = "bake"
    FORBIDDEN = "forbidden"


class RoundTrip(StrEnum):
    EXACT = "exact"
    NORMALIZED = "normalized"
    LOSSY = "lossy"
    DROPPED = "dropped"


_REQUIRED: Final[dict[Disposition, frozenset[str]]] = {
    Disposition.NATIVE: frozenset({"selector", "canonical", "maps_to"}),
    Disposition.NORMALIZE: frozenset({"normalizes_to", "normalizer", "canonical", "severity"}),
    Disposition.BAKE: frozenset({"selector", "bake"}),
    Disposition.FORBIDDEN: frozenset({"selector", "msg"}),
}
"""09 section 3.4's table, plus the selector every row but a normalize row carries."""

_FORBIDDEN: Final[dict[Disposition, frozenset[str]]] = {
    Disposition.NATIVE: frozenset({"normalizer", "normalizes_to", "bake", "severity"}),
    Disposition.NORMALIZE: frozenset({"selector", "maps_to", "bake", "forbidden_when"}),
    Disposition.BAKE: frozenset(
        {"canonical", "maps_to", "normalizer", "normalizes_to", "severity"}
    ),
    Disposition.FORBIDDEN: frozenset(
        {"canonical", "maps_to", "normalizer", "normalizes_to", "bake", "severity"}
    ),
}
"""09 section 3.4's table, plus ruling 2's `severity`."""

_ROUND_TRIPS: Final[dict[Disposition, frozenset[RoundTrip]]] = {
    Disposition.BAKE: frozenset({RoundTrip.LOSSY}),
    Disposition.FORBIDDEN: frozenset({RoundTrip.LOSSY, RoundTrip.DROPPED}),
}


@dataclass(frozen=True, slots=True)
class Bake:
    """`bake = { renderer, dpi, role }`."""

    renderer: str
    dpi: int
    role: str


@dataclass(frozen=True, slots=True)
class Construct:
    """One row. A normalize row's `selector` is the one it inherits from its native row."""

    id: str
    disposition: Disposition
    round_trip: RoundTrip
    code: str
    since: str
    selector: str
    canonical: str | None = None
    maps_to: str | None = None
    normalizes_to: str | None = None
    normalizer: str | None = None
    bake: Bake | None = None
    forbidden_when: str | None = None
    msg: str | None = None
    severity: str | None = None
    visible: bool = True


@dataclass(frozen=True, slots=True)
class ConstructTable:
    """A loaded, asserted `constructs.toml`."""

    carrier: str
    il: str
    version: int
    ignore: tuple[str, ...]
    rows: tuple[Construct, ...]
    sha256: str
    """Ruling 7: `sha256:` and the canonical digest of the table as loaded."""

    @classmethod
    def load(cls, path: Path, normalizers: Mapping[str, Callable[[str], str]]) -> ConstructTable:
        """Read and assert one table; `normalizers` is the target's `normalizers.py` by name."""
        try:
            raw = tomllib.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, tomllib.TOMLDecodeError) as exc:
            _fail(f"{path.name} does not load: {exc}")
        return cls.parse(raw, normalizers, source=path.name)

    @classmethod
    def parse(
        cls, raw: Mapping[str, Any], normalizers: Mapping[str, Callable[[str], str]], *, source: str
    ) -> ConstructTable:
        """`load()` over an already-read TOML document."""
        unknown = sorted(set(raw) - _TOP_KEYS)
        if unknown:
            _fail(f"{source}: unknown key(s) {unknown} (ruling 1)")
        if raw.get("schema") != CONSTRUCTS_SCHEMA:
            _fail(f"{source}: schema {raw.get('schema')!r} is not {CONSTRUCTS_SCHEMA!r}")
        carrier = raw.get("carrier")
        if carrier not in _CARRIERS:
            _fail(f"{source}: carrier {carrier!r} is not one of {sorted(_CARRIERS)}")
        if raw.get("unknown_construct") != "forbidden":
            _fail(
                f'{source}: unknown_construct must be "forbidden"; fail-closed is not configurable'
            )
        version = raw.get("version")
        if not isinstance(version, int) or isinstance(version, bool) or version < 1:
            _fail(f"{source}: version {version!r} is not a positive integer")
        il = raw.get("il")
        if not isinstance(il, str) or not il:
            _fail(f"{source}: il {il!r} is not an IL id")
        ignore = tuple(_strings(raw.get("ignore", []), f"{source}: ignore"))
        for selector in ignore:
            _selector(selector, carrier, f"{source}: ignore")
        entries = raw.get("construct", [])
        if not isinstance(entries, list) or not entries:
            _fail(f"{source}: no [[construct]] rows")
        drafts = [_row(entry, carrier, source) for entry in entries]
        rows = _resolve(drafts, normalizers, source)
        _mandatory(rows, carrier, source)
        return cls(
            carrier=carrier,
            il=il,
            version=version,
            ignore=ignore,
            rows=rows,
            sha256="sha256:" + sha256_canonical(dict(raw)),
        )

    def digest(self) -> str:
        """`ConstructTable.load().digest()`, 09 section 3.6's spelling: the card's
        `constructs_digest` and a bundle's are compared against it."""
        return self.sha256

    def row(self, construct_id: str) -> Construct:
        for row in self.rows:
            if row.id == construct_id:
                return row
        raise KeyError(construct_id)

    def conditional(self, doc: CarrierDoc) -> tuple[Construct, ...]:
        """The rows whose `forbidden_when` holds in this unit (09 section 3.1 rule 5).

        Per unit, not per node: does anything in the unit match the condition. The framework
        evaluates it from the table, so a rule only reports it.
        """
        return tuple(
            row
            for row in self.rows
            if row.forbidden_when is not None and doc.select(row.forbidden_when)
        )


def _row(entry: object, carrier: str, source: str) -> dict[str, Any]:
    if not isinstance(entry, dict):
        _fail(f"{source}: a [[construct]] row is not a table")
    where = f"{source}: construct {entry.get('id')!r}"
    unknown = sorted(set(entry) - _ROW_KEYS)
    if unknown:
        _fail(f"{where}: unknown key(s) {unknown} (ruling 1)")
    for key in ("id", "disposition", "round_trip", "code", "since"):
        if not isinstance(entry.get(key), str) or not entry[key]:
            _fail(f"{where}: {key} is required")
    _shape(entry, where)
    if _SYMBOL.fullmatch(entry["code"]) is None:
        _fail(f"{where}: code {entry['code']!r} is not a codes.toml symbol")
    if _VERSION.fullmatch(entry["since"]) is None:
        _fail(f"{where}: since {entry['since']!r} is not a version (ruling 6)")
    if "bake" in entry:
        bake = entry["bake"]
        if not isinstance(bake, dict) or frozenset(bake) != _BAKE_KEYS:
            _fail(f"{where}: bake is {{ renderer, dpi, role }}")
    if "visible" in entry and not isinstance(entry["visible"], bool):
        _fail(f"{where}: visible is true or false")
    for key in ("selector", "forbidden_when"):
        if key in entry:
            _selector(entry[key], carrier, f"{where}: {key}")
    return dict(entry)


def _shape(entry: Mapping[str, Any], where: str) -> None:
    """09 section 3.4's per-disposition table: what the row must carry and may not."""
    try:
        disposition = Disposition(entry["disposition"])
        round_trip = RoundTrip(entry["round_trip"])
    except ValueError as exc:
        _fail(f"{where}: {exc}")
    missing = sorted(_REQUIRED[disposition] - set(entry))
    if missing:
        _fail(f"{where}: a {disposition} row requires {missing}")
    present = sorted(_FORBIDDEN[disposition] & set(entry))
    if present:
        _fail(f"{where}: a {disposition} row may not carry {present}")
    allowed = _ROUND_TRIPS.get(disposition)
    if allowed is not None and round_trip not in allowed:
        _fail(f"{where}: a {disposition} row's round_trip is one of {sorted(allowed)}")
    if disposition is Disposition.NORMALIZE and entry["severity"] != "warning":
        _fail(f"{where}: a normalize row is a warning, never an error")


def _resolve(
    drafts: Sequence[dict[str, Any]], normalizers: Mapping[str, Callable[[str], str]], source: str
) -> tuple[Construct, ...]:
    by_id: dict[str, dict[str, Any]] = {}
    for draft in drafts:
        if draft["id"] in by_id:
            _fail(f"{source}: construct {draft['id']!r} is declared twice")
        by_id[draft["id"]] = draft
    rows = []
    for draft in drafts:
        where = f"{source}: construct {draft['id']!r}"
        selector: str = draft.get("selector", "")
        if draft["disposition"] == Disposition.NORMALIZE:
            target = by_id.get(draft["normalizes_to"])
            if target is None or target["disposition"] != Disposition.NATIVE:
                _fail(f"{where}: normalizes_to {draft['normalizes_to']!r} is not a native row")
            if draft["normalizer"] not in normalizers:
                _fail(f"{where}: normalizer {draft['normalizer']!r} is not in normalizers.py")
            selector = target["selector"]
        bake = draft.get("bake")
        rows.append(
            Construct(
                id=draft["id"],
                disposition=Disposition(draft["disposition"]),
                round_trip=RoundTrip(draft["round_trip"]),
                code=draft["code"],
                since=draft["since"],
                selector=selector,
                canonical=draft.get("canonical"),
                maps_to=draft.get("maps_to"),
                normalizes_to=draft.get("normalizes_to"),
                normalizer=draft.get("normalizer"),
                bake=None
                if bake is None
                else Bake(str(bake["renderer"]), int(bake["dpi"]), str(bake["role"])),
                forbidden_when=draft.get("forbidden_when"),
                msg=draft.get("msg"),
                severity=draft.get("severity"),
                visible=draft.get("visible", True),
            )
        )
    return tuple(rows)


def _mandatory(rows: Sequence[Construct], carrier: str, source: str) -> None:
    """Ruling 4: an attribute selector's attribute, or an element selector's qualifier."""
    named = {parse_selector(row.selector, carrier).name for row in rows}
    missing = [a for a in MANDATORY_ATTRIBUTES if a not in named]
    if missing:
        _fail(f"{source}: no row names the mandatory attribute(s) {missing}")


def _selector(value: object, carrier: str, where: str) -> Selector:
    if not isinstance(value, str):
        _fail(f"{where}: {value!r} is not a selector")
    try:
        return parse_selector(value, carrier)
    except TargetError as exc:
        raise TargetError(
            f"{where}: {exc}", symbol="OW_TARGET_SELECTOR_INVALID", fix=_FIX
        ) from None


def _strings(value: object, where: str) -> list[str]:
    if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
        _fail(f"{where} is not a list of strings")
    return value


def _fail(msg: str) -> Never:
    raise TargetError(msg, symbol="OW_TARGET_CONSTRUCTS_INVALID", fix=_TABLE_FIX)
