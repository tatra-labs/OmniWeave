"""A compile card's `[compile]` tables, read strictly, and the target listing. **D760.**

09-generation.md section 12.4: "`[compile]` is a **hard-error-on-unknown-key** table precisely so
an older core cannot silently drop `implemented = false` and treat the driver as implemented with
unbounded units. `[capability.compile]` keeps the ignore-with-degradation asymmetry, because its
keys are all set-valued floors where an unrecognised member can only make a driver look *less*
capable." `drivers.card.load_card()` carries both tables verbatim (D244's ruling), so this module
is where they are read, and it reads them the way 09 says.

## Rulings

1. **`[compile]` is closed, and a card that breaks it is `OW_CARD_INVALID`.** That covers an
   unknown key, a missing key, a value outside its vocabulary, and a `round_trip` that
   `roundtrip.applicable()` refuses. A compile card is a contract like any other card, and the
   card grammar's refusal is the one this reuses.
2. **`implemented = false` needs a `reason`.** 09 says `ow out targets` prints "the target, the
   flag and **the reason**", and no card printed in 09 or the API sketch carries a key for it. So
   `reason` is `[compile]`'s one addition. It is required exactly when the target is not
   implemented, and an implemented target may not carry one. An unimplemented target may also
   leave `constructs` and `constructs_digest` empty: video's table "was never written" and is not
   to be designed from an index page (section 12.4).
3. **`[capability.compile]` ignores what it does not know, and says so.** `determinism` must
   contain `part`, the floor every target has. An unrecognised determinism class or asset role
   is dropped and recorded as a degradation on the `CompileCard`, never an error, because an
   unknown member can only shrink a set-valued floor.
4. **`targets()` lists compile cards as rows**, sorted by target and then driver. Each row carries
   the target, the driver, the flag, the reason, the carrier, the IL, the fidelity, the laws and
   the declared determinism (D761: 10-interfaces.md's `ow_targets` row lists "their determinism
   class"). That is what `ow out targets` prints, and `as_json()` is the shape `--render json`
   emits. Two cards claiming one target are both listed, because choosing one is the
   registry's decision.
5. **A target that names a table declares `agent_doc_tokens_max`** (D762). 09 section 3.5 item
   5 gates every target's agent document at it, so a table without one would have no gate. An
   implemented target names a table, so it always declares one. D781: an unimplemented target
   may name its table too (docx, gated before it lowers), and then declares its budget; one
   with no table has nothing to document and may leave it out.
6. **An implemented target declares `media_type` and `suffix`** (D770). The artefact row's
   `media_type` is `NOT NULL` and its path is `<slug>@<gen>/<slug><suffix>` (D755), and
   no printed card names either: the API sketch's `[capability] formats` is the parse
   routing key, a media type a driver reads, not one it writes. `media_type` is a
   `type/subtype` token and `suffix` a dot and 1 to 8 lower-case letters or digits.
7. **A `passthrough` card names each unit's part** (D808). R4 compares the part a unit
   lowers to with the part its source lowered to, and 09 section 11.4 makes R4 meaningful
   only where container parts are copyable. So `[compile.round_trip] unit_part` is
   required exactly when `fidelity = "passthrough"`: a package member path that
   holds `{ord}` once, which `part_of()` fills with a unit's `ord`. pptx's is
   `ppt/slides/slide{ord}.xml`.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Final, NoReturn

from omniweave_core.errors import DriverHostError
from omniweave_core.out.ledger import ROLES
from omniweave_core.out.receipt import ArtefactDeterminism
from omniweave_core.out.roundtrip import applicable

if TYPE_CHECKING:
    from omniweave_core.drivers.card import DriverCard

__all__ = ["COMPILE_KEYS", "ROUND_TRIP_KEYS", "CompileCard", "TargetRow", "part_of", "targets"]

COMPILE_KEYS: Final = frozenset(
    {
        "target",
        "unit",
        "carrier",
        "il",
        "constructs",
        "constructs_digest",
        "citations",
        "provenance_part",
        "bake",
        "measure",
        "runtime_rules",
        "toolchain",
        "implemented",
        "max_units",
        "agent_doc_tokens_max",
        "media_type",
        "suffix",
        "reason",
        "round_trip",
    }
)
"""`[compile]`'s keys: the API sketch's card, plus `reason` (ruling 2)."""
ROUND_TRIP_KEYS: Final = frozenset({"read_back", "project", "fidelity", "laws", "kind_map"})
UNIT_PART: Final = "unit_part"
"""Ruling 7: `[compile.round_trip]`'s one optional key, required with `passthrough`."""
_OPTIONAL: Final = frozenset(
    {"reason", "provenance_part", "toolchain", "agent_doc_tokens_max", "media_type", "suffix"}
)
_TOKEN: Final = re.compile(r"[a-z][a-z0-9_-]{0,31}")
_IL: Final = re.compile(r"[a-z][a-z0-9_-]{0,31}/[1-9][0-9]*")
_DIGEST: Final = re.compile(r"sha256:[0-9a-f]{64}")
_MEDIA_TYPE: Final = re.compile(r"[a-z0-9][a-z0-9!#$&^_.+-]{0,63}/[a-z0-9][a-z0-9!#$&^_.+-]{0,126}")
_SUFFIX: Final = re.compile(r"\.[a-z0-9]{1,8}")
_PART: Final = re.compile(r"[A-Za-z0-9_.-]+(?:/[A-Za-z0-9_.-]+)*")
_ORD: Final = "{ord}"
_CARRIERS: Final = frozenset({"svg", "html"})
_CITATIONS: Final = frozenset({"embedded", "sidecar"})
_BAKE: Final = frozenset({"available", "unavailable"})
_DETERMINISM: Final = frozenset(d.value for d in ArtefactDeterminism)


@dataclass(frozen=True, slots=True)
class CompileCard:
    """`[compile]`, `[compile.round_trip]` and `[capability.compile]`, read strictly."""

    driver: str
    target: str
    unit: str
    carrier: str
    il: str
    constructs: str
    constructs_digest: str
    citations: str
    bake: str
    measure: str
    runtime_rules: bool
    toolchain: str
    implemented: bool
    max_units: int
    reason: str
    read_back: str
    project: bool
    fidelity: str
    laws: tuple[str, ...]
    kind_map: str
    determinism: tuple[str, ...]
    assets: tuple[str, ...]
    agent_doc_tokens_max: int = 0
    media_type: str = ""
    """Ruling 6: the artefact's media type; `""` only when not implemented."""
    suffix: str = ""
    """Ruling 6: the artefact's file suffix, `.txt`; `""` only when not implemented."""
    """Ruling 5: the ceiling on `ow out constructs --format md`; 0 only when not implemented."""
    degradations: tuple[str, ...] = ()
    """Ruling 3: what `[capability.compile]` named and this core does not know."""
    unit_part: str = ""
    """Ruling 7: the member a unit lowers to, `{ord}` its place; `""` unless `passthrough`."""

    def part_of(self, ord_: int) -> str:
        """Ruling 7: the package member the unit at `ord_` lowers to."""
        return part_of(self.unit_part, ord_)

    @classmethod
    def of(cls, card: DriverCard) -> CompileCard:
        """Rulings 1-3 over one discovered card."""
        source = str(card.source)
        sibling = dict(card.compile_sibling)
        unknown = sorted(set(sibling) - COMPILE_KEYS)
        if unknown:
            _invalid(source, f"[compile] has unknown key(s) {unknown}: the table is closed")
        missing = sorted(COMPILE_KEYS - _OPTIONAL - set(sibling))
        if missing:
            _invalid(source, f"[compile] is missing {missing}")
        implemented = _bool(source, sibling, "implemented")
        reason = str(sibling.get("reason", ""))
        if implemented == bool(reason):
            _invalid(
                source,
                "[compile] reason is required exactly when implemented = false"
                if not implemented
                else "[compile] reason is only for a target with implemented = false",
            )
        round_trip = sibling["round_trip"]
        if not isinstance(round_trip, Mapping):
            _invalid(source, "[compile.round_trip] is not a table")
        rt = dict(round_trip)
        if set(rt) - {UNIT_PART} != ROUND_TRIP_KEYS:
            _invalid(
                source, f"[compile.round_trip] keys {sorted(rt)} are not {sorted(ROUND_TRIP_KEYS)}"
            )
        fidelity = str(rt["fidelity"])
        unit_part = _unit_part(source, rt, fidelity)
        raw_laws = rt["laws"]
        if not isinstance(raw_laws, list) or not all(isinstance(law, str) for law in raw_laws):
            _invalid(source, "[compile.round_trip] laws is not a list of law names")
        laws = tuple(str(law) for law in raw_laws)
        try:
            applicable(laws, fidelity)
        except ValueError as exc:
            _invalid(source, f"[compile.round_trip] {exc}")
        determinism, assets, degraded = _capability(source, dict(card.compile_capability))
        built = cls(
            driver=str(card.identity.id),
            target=_match(source, sibling, "target", _TOKEN),
            unit=_match(source, sibling, "unit", _TOKEN),
            carrier=_member(source, sibling, "carrier", _CARRIERS),
            il=_match(source, sibling, "il", _IL),
            constructs=str(sibling["constructs"]),
            constructs_digest=str(sibling["constructs_digest"]),
            citations=_member(source, sibling, "citations", _CITATIONS),
            bake=_member(source, sibling, "bake", _BAKE),
            measure=str(sibling["measure"]),
            runtime_rules=_bool(source, sibling, "runtime_rules"),
            toolchain=str(sibling.get("toolchain", "")),
            implemented=implemented,
            max_units=_positive(source, sibling, "max_units"),
            agent_doc_tokens_max=(
                _positive(source, sibling, "agent_doc_tokens_max")
                if "agent_doc_tokens_max" in sibling
                else 0
            ),
            media_type=(
                _match(source, sibling, "media_type", _MEDIA_TYPE)
                if "media_type" in sibling
                else ""
            ),
            suffix=_match(source, sibling, "suffix", _SUFFIX) if "suffix" in sibling else "",
            reason=reason,
            read_back=str(rt["read_back"]),
            project=_bool(source, rt, "project"),
            fidelity=fidelity,
            laws=laws,
            kind_map=str(rt["kind_map"]),
            determinism=determinism,
            assets=assets,
            degradations=degraded,
            unit_part=unit_part,
        )
        if implemented and (
            not built.constructs or _DIGEST.fullmatch(built.constructs_digest) is None
        ):
            _invalid(source, "an implemented target names its constructs and a sha256 digest")
        if built.constructs and not built.agent_doc_tokens_max:
            _invalid(
                source, "a target naming a table declares agent_doc_tokens_max (09 section 3.5)"
            )
        if implemented and not (built.media_type and built.suffix):
            _invalid(source, "an implemented target declares its media_type and suffix (D770)")
        return built


def part_of(unit_part: str, ord_: int) -> str:
    """Ruling 7: `unit_part` filled with a unit's `ord`, the member it lowers to."""
    return unit_part.replace(_ORD, str(ord_))


def _unit_part(source: str, rt: Mapping[str, Any], fidelity: str) -> str:
    """Ruling 7: required with `passthrough`, refused without, and holding `{ord}` once."""
    passthrough = fidelity == "passthrough"
    if (UNIT_PART in rt) != passthrough:
        _invalid(
            source,
            "[compile.round_trip] unit_part is required exactly when fidelity = passthrough",
        )
    if not passthrough:
        return ""
    part = str(rt[UNIT_PART])
    if part.count(_ORD) != 1 or _PART.fullmatch(part.replace(_ORD, "1")) is None:
        _invalid(
            source,
            f"[compile.round_trip] unit_part {part!r} is not a member path holding {_ORD} once",
        )
    return part


def _capability(
    source: str, capability: Mapping[str, Any]
) -> tuple[tuple[str, ...], tuple[str, ...], tuple[str, ...]]:
    """Ruling 3: `part` is required; an unknown member is dropped and recorded."""
    declared = [str(d) for d in capability.get("determinism", [])]
    if "part" not in declared:
        _invalid(source, "[capability.compile] determinism must include part, the floor")
    roles = [str(r) for r in capability.get("assets", [])]
    degraded = [
        f"determinism {d!r} is unknown and was ignored" for d in declared if d not in _DETERMINISM
    ]
    degraded += [f"asset role {r!r} is unknown and was ignored" for r in roles if r not in ROLES]
    return (
        tuple(d for d in declared if d in _DETERMINISM),
        tuple(r for r in roles if r in ROLES),
        tuple(degraded),
    )


@dataclass(frozen=True, slots=True)
class TargetRow:
    """Ruling 4: one line of `ow out targets`."""

    target: str
    driver: str
    implemented: bool
    reason: str
    carrier: str
    il: str
    fidelity: str
    laws: tuple[str, ...]
    determinism: tuple[str, ...] = ()

    def as_json(self) -> dict[str, Any]:
        return {
            "target": self.target,
            "driver": self.driver,
            "implemented": self.implemented,
            "reason": self.reason,
            "carrier": self.carrier,
            "il": self.il,
            "fidelity": self.fidelity,
            "laws": list(self.laws),
            "determinism": list(self.determinism),
        }

    def line(self) -> str:
        flag = "implemented" if self.implemented else f"implemented = false: {self.reason}"
        return f"{self.target:<8} {self.driver:<24} {self.carrier}/{self.il}  {flag}"


def targets(cards: Iterable[DriverCard]) -> tuple[TargetRow, ...]:
    """Ruling 4: every `compile/1` card as a row, sorted by target then driver."""
    rows = []
    for card in cards:
        if str(card.identity.port) != "compile":
            continue
        c = CompileCard.of(card)
        rows.append(
            TargetRow(
                c.target,
                c.driver,
                c.implemented,
                c.reason,
                c.carrier,
                c.il,
                c.fidelity,
                c.laws,
                c.determinism,
            )
        )
    return tuple(sorted(rows, key=lambda r: (r.target, r.driver)))


def _invalid(source: str, message: str) -> NoReturn:
    raise DriverHostError(
        f"{source}: {message}", symbol="OW_CARD_INVALID", fix=f"ow drivers check {source}"
    )


def _match(source: str, table: Mapping[str, Any], key: str, pattern: re.Pattern[str]) -> str:
    value = table[key]
    if not isinstance(value, str) or pattern.fullmatch(value) is None:
        _invalid(source, f"[compile] {key} = {value!r} does not match {pattern.pattern}")
    return value


def _member(source: str, table: Mapping[str, Any], key: str, allowed: frozenset[str]) -> str:
    value = table[key]
    if value not in allowed:
        _invalid(source, f"[compile] {key} = {value!r} is not one of {sorted(allowed)}")
    return str(value)


def _bool(source: str, table: Mapping[str, Any], key: str) -> bool:
    value = table[key]
    if not isinstance(value, bool):
        _invalid(source, f"{key} = {value!r} is not a boolean")
    return value


def _positive(source: str, table: Mapping[str, Any], key: str) -> int:
    value = table[key]
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        _invalid(source, f"[compile] {key} = {value!r} is not a positive integer")
    return value
