"""anydoc's fixed limits, the one vocabulary a user sees, and the boundary that refuses to guess.

14-security.md §2.10 is this module's whole warrant, and its first sentence is the one that makes
the module necessary: anydoc's constants are compile-time and **deliberately not configurable**
(`vendor/anydoc/src/package/limits.rs:1-8`, "They are deliberately not configurable: real-world
documents sit orders of magnitude below every value here").

Three consequences the plan states rather than leaves to discovery:

1. **On the office path the Rust constant IS `HOST_MAX`.** `effective = min(tenant_cap, declared,
   HOST_MAX)` still holds, and a tenant can still clamp *down* by refusing a unit before it crosses
   the FFI -- but nothing clamps down *inside* the Rust walk. The memory a hostile ODS can reach
   before the Rust side refuses is anydoc's number, not the tenant's (14:495-497).
2. **A `ResourceLimit` returns as `DriverError(RESOURCE_LIMIT, limit=...)` carrying anydoc's own
   limit name**, and `codes.toml` maps those names onto omniweave's vocabulary so a user reads one
   (14:502-505). `NAMES` below is that map's driver-side half.
3. **A name anydoc adds that omniweave has no row for is `OW_SCHEMA_UNKNOWN_KIND` at the boundary,
   never a silent pass-through** (14:505). `classify()` is where that happens, and it is the reason
   this module exists at all rather than the driver passing `exc.limit` straight through.

## Eleven, not twelve

The plan says "twelve" in five places (05:186, 14:489, 14:504, 14:1724, 16:1137). The pinned
wheel's source has **eleven** `pub const` in `src/package/limits.rs` and **eleven** distinct
`ConvertError::ResourceLimit { limit: "..." }` spellings across the whole crate, and the two sets
are in bijection. `_plan/_notes/build-defects.md` D123 records the count with the command that
produced it. This module carries the verified number, on the same principle 03 §18 Q10 applies to
the `Block`-variant count: state the verified number, record the divergence, do not propagate it.

## The parity test lives next door, and why it is not here

14:498 asks for "a parity test [asserting] that every `MAX_*` in `omniweave_core.limits` that
names a vector anydoc also bounds has a value greater than or equal to anydoc's, so the
Python-side ceiling can never be the tighter one silently". That test imports `omniweave_core`,
which
`tools/layers.toml` forbids this package to do (`omniweave_office = ["omniweave_ports"]`). It is
therefore in `tests/unit/test_office_limits.py`, which is test code and may import anything, and in
`tools/gate_vendor.py`, which is neither a package nor a driver. What lives *here* is the data the
test joins on -- which is also the data the driver needs at runtime, so there is one home for it
(INV-21) rather than one for the gate and one for the boundary.
"""

from __future__ import annotations

from collections.abc import Mapping
from types import MappingProxyType
from typing import Final, NamedTuple

__all__ = [
    "CEILINGS",
    "NAMES",
    "UNKNOWN_LIMIT",
    "AnydocLimit",
    "classify",
]

UNKNOWN_LIMIT: Final = "OW_SCHEMA_UNKNOWN_KIND"
"""What an unrecognised limit name becomes. 14-security.md:505, and the code is
`03-document-model.md:151`'s: a reader that meets a kind it does not know says so, and does
not guess.

It is deliberately NOT a new `limit` string. A boundary that invented `max_whatever_anydoc_said`
would put an unregistered name into a `DriverError.limit` field that `codes.toml` is supposed to be
the total map of, and the next reader could not tell an unmapped name from a mapped one."""


class AnydocLimit(NamedTuple):
    """One of anydoc's eleven ceilings: its own name, its value, and omniweave's counterpart.

    `core` names the constant in `omniweave_core.limits` that bounds the SAME vector. It is a
    string rather than the value because this package may not import core; the parity test resolves
    it, which is also the moment a renamed core constant is caught.
    """

    value: int
    core: str
    vector: str


CEILINGS: Final[Mapping[str, AnydocLimit]] = MappingProxyType(
    {
        "max_entry_bytes": AnydocLimit(
            134_217_728, "MAX_ENTRY_BYTES", "one archive entry, decompressed"
        ),
        "max_total_bytes": AnydocLimit(
            536_870_912, "MAX_CONTAINER_TOTAL_BYTES", "all entries of one archive, decompressed"
        ),
        "max_entry_count": AnydocLimit(100_000, "MAX_ENTRY_COUNT", "entries in one archive"),
        "max_xml_depth": AnydocLimit(256, "MAX_XML_DEPTH", "XML element nesting"),
        "max_xml_nodes": AnydocLimit(
            2_000_000, "MAX_XML_NODES", "XML elements plus text runs in one part"
        ),
        "max_grid_slots": AnydocLimit(
            4_000_000, "MAX_GRID_SLOTS", "grid positions one sheet may materialise"
        ),
        "max_expansion": AnydocLimit(
            4_000_000, "MAX_EXPANSION", "content-bearing cells one repeat expansion may produce"
        ),
        "max_expansion_text_bytes": AnydocLimit(
            67_108_864, "MAX_EXPANSION_TEXT_BYTES", "text bytes duplicated by repeat expansion"
        ),
        "max_asset_total_bytes": AnydocLimit(
            134_217_728, "MAX_ASSET_TOTAL_BYTES", "retained embedded-asset bytes in one document"
        ),
        "max_record_depth": AnydocLimit(
            64, "MAX_RECORD_DEPTH", "legacy CFB record-container nesting"
        ),
        "max_records": AnydocLimit(
            16_000_000, "MAX_RECORDS", "records visited in one legacy record stream"
        ),
    }
)
"""The eleven, keyed by the string anydoc raises. Values read off
`vendor/anydoc/src/package/limits.rs` at commit 261fc257.

`max_asset_total_bytes` is the row 05:212 singles out and it is the one place the two sides differ
in kind rather than in value: anydoc's is 128 MiB while core's `MAX_ASSET_TOTAL_BYTES` is 512 MiB,
because core's is **derived** -- the charter's per-asset ceiling `MAX_ASSET_BYTES` is 256 MiB, so a
whole-document budget below it would make a single legal maximum-size asset unrepresentable. The
parity direction still holds (`core >= anydoc`), which is the only thing the test asserts, and the
consequence is the one 14:496 names: on this path the tighter number is the Rust one and a tenant
cannot widen it."""

NAMES: Final[tuple[str, ...]] = tuple(CEILINGS)
"""The eleven names in declaration order. `tuple(CEILINGS)` rather than a second literal list --
INV-21, one home for one fact, and a list that could disagree with the map is the defect."""


def classify(limit: str | None) -> str:
    """anydoc's limit name, or `OW_SCHEMA_UNKNOWN_KIND` for one this release does not know.

    The two answers are deliberately different *shapes* of string -- a lowercase knob name versus a
    screaming-snake code -- so a `DriverError.limit` a user reads, a `codes.toml` lookup and a log
    grep all tell them apart without a schema. 14-security.md:505 asks for exactly this and calls
    the alternative "a silent pass-through".

    `None` is `UNKNOWN_LIMIT` too: `ResourceLimitError` always sets `limit` (the binding is
    `vendor/anydoc/python/src/lib.rs:130-132`), so a `None` here means the wheel changed shape,
    which is the same class of event as a new name and gets the same answer.
    """
    if limit in CEILINGS:
        return str(limit)
    return UNKNOWN_LIMIT
