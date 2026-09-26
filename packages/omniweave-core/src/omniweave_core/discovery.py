"""Metadata-only discovery: find every `driver.toml` on the machine and read none of the code.

This module is INV-4's implementation. It enumerates entry points, scans two directory roots and
the framework's own tombstone package data, locates each named package's `driver.toml` through
`Distribution.locate_file()`, and hands the bytes to `omniweave_core.drivers.card.load_card()`.
**It never imports a driver.** `EntryPoint.load()`, `importlib.import_module` and `__import__` are
absent by construction and banned by `tools/semgrep/omniweave.yaml`; `omniweave_core/host/`'s
`activate()` is the one site in the framework that executes driver code, after it has asserted the
loaded class's `PORT` and `SCHEMA_VERSION` (04-driver-system.md section 4.6, 02-architecture.md
section 2 row 12).

**Scanning `Distribution.files` / `RECORD` to find cards is forbidden.** It was measured at
**2124 ms** for 328 installed distributions against a claimed 1-4 ms — three orders of magnitude
wrong, on the discovery path (04-driver-system.md section 4.1). A card is located by *name*:
`Distribution.locate_file(value.replace(".", "/") + "/driver.toml")`, one path join per driver. The
`driver_card_cache` validity key is the counterpart measurement — `os.scandir` + `stat` of every
`*.dist-info` at **1.01 ms** for the same 328 distributions, which is precisely why the cache is
validated wholesale rather than per card (section 4.3).

**Discovery never raises.** A broken neighbour cannot stop a catalog (section 4.5). Every refusal
`load_card()` would raise is caught and recorded as a `DiscoveryFault`; an entry point whose card
is missing is additionally a `DiscoveryDegradation(kind="driver_unavailable")` naming the
distribution. The one thing that propagates is a programming error in this module.

**Nothing here happens at process start.** `import omniweave_core` performs no discovery, no
`entry_points()` and no `tomllib` (section 4.3); `Catalog.build()` calls `discover()` once per run
at the first `Requirement` for a Port, and the result is never rebuilt mid-run.

Scope boundary: this module produces the *materials* for a catalog — cards, tombstones, faults,
degradations and the validity key. `omniweave_core.drivers.catalog` owns the `Catalog` dataclass,
`catalog_digest` and the probe verdicts; `omniweave_core.registry` owns `Registry` and
`DuplicateDriver`; `resolve()` and `activate()` are elsewhere again. Discovery does not activate,
resolve, probe, import or compute trust.

Specified in 04-driver-system.md sections 4.1, 4.3, 4.4, 4.5 and 4.6; 02-architecture.md section 2
row 12; 01-principles.md INV-4; 16-roadmap.md W1.5.
"""

from __future__ import annotations

import json
import os
import re
import sys
import time
from dataclasses import dataclass, field
from importlib.metadata import Distribution
from pathlib import Path
from types import MappingProxyType
from typing import TYPE_CHECKING, Final, Protocol
from urllib.parse import unquote, urlsplit

from omniweave_core.drivers.card import (
    DriverCard,
    Tombstone,
    load_card,
    read_card_bytes,
)
from omniweave_core.drivers.catalog import (
    Catalog,
    compute_trust,
    compute_validity_key,
    read_first_party,
)
from omniweave_core.errors import DriverHostError

if TYPE_CHECKING:  # pragma: no cover - imported for annotations only, so G17's budget is unpaid
    from collections.abc import Callable, Iterable, Mapping, Sequence

    from omniweave_ports.types import TrustTier

    from omniweave_core.drivers.card import CardOrigin
    from omniweave_core.drivers.catalog import FirstPartyManifest

__all__ = [
    "BACKEND_GROUP",
    "CARD_FILENAME",
    "DISCOVERY_CEILING_MS",
    "DISCOVERY_DEGRADATION_KINDS",
    "DIST_INFO_SUFFIXES",
    "DRIVER_GROUP",
    "DRIVER_PATH_ENV",
    "OPERATOR_GROUP",
    "PACKAGE_PATH_RE",
    "PROJECT_DRIVER_DIR",
    "TARGET_GROUP",
    "TIMED_STEPS",
    "TOMBSTONE_DIRNAME",
    "CardCache",
    "CardCacheRow",
    "CardSource",
    "DiscoveredCard",
    "Discovery",
    "DiscoveryDegradation",
    "DiscoveryFault",
    "EntryPointRef",
    "LoadOutcome",
    "MemoryCardCache",
    "card_relative_path",
    "catalog",
    "discover",
    "dist_info_triples",
    "driver_path_sources",
    "entry_point_refs",
    "entry_point_sources",
    "entry_point_value_fault",
    "is_editable",
    "load_one",
    "project_sources",
    "tombstone_sources",
    "validity_key",
]


# --------------------------------------------------------------------------------------------
# 1. The names. Four origins, four entry-point groups, one filename.
# --------------------------------------------------------------------------------------------

DRIVER_GROUP: Final[str] = "omniweave.drivers"
"""The entry-point group every driver is declared in, whatever its Port.

`[project.entry-points."omniweave.drivers"] "<id>" = "<dotted.package>"`: the NAME is the
`DriverId` and the VALUE is a colon-free dotted package path. **This is the only group cards are
read from.** A `compile` driver is declared here like every other driver and is *additionally*
aliased in `TARGET_GROUP`; section 5 X5 settles it — both groups stand and both gates apply — so
reading cards from both would load one `driver.toml` twice under two different keys.

04-driver-system.md section 4.1."""

TARGET_GROUP: Final[str] = "omniweave.targets"
"""`"pptx" = "omniweave_target_pptx"` — an ARTEFACT ALIAS, not a driver id and not a card.

It exists so `ow out targets` can list an artefact kind **without resolving a driver**. Neither
this list nor `[drivers] enabled` bypasses the other, and `ow doctor` fails on a `[targets]
enabled` entry whose `compile` driver is absent from `[drivers] enabled`. Discovery enumerates it
and validates the value's grammar; it mints no card from it (04-driver-system.md section 4.1)."""

BACKEND_GROUP: Final[str] = "omniweave.backends"
"""`VectorBackend` declarations, read by this same import-free loader (04-driver-system.md
section 4.1). A backend is not a Driver and carries no `driver.toml`, so — like `TARGET_GROUP` —
it is enumerated as an `EntryPointRef` and never located as a card."""

OPERATOR_GROUP: Final[str] = "omniweave.operators"
"""**Reserved and uncreated.** Named here so the reservation is greppable and so a test can assert
discovery does not read it: an operator is not separately registered at release 1, and a group
that quietly began working would make the reservation meaningless (04-driver-system.md
section 4.1)."""

CARD_FILENAME: Final[str] = "driver.toml"
"""The one filename. Every origin ends at a file with this name — inside the named package for
`entry_point`, inside `<dir>/*/` for `driver_path` and `project`. Only the framework's own
tombstones live under a different name, because they are `*.toml` package data rather than a
driver's own declaration (04-driver-system.md section 4.1)."""

DRIVER_PATH_ENV: Final[str] = "OMNIWEAVE_DRIVER_PATH"
"""The env var naming directories scanned **depth-1** for `*/driver.toml`, trust `local`.

It is how a driver participates without being installed as a wheel, and it is the home of the
`exec` (non-Python driver) form — `exec` is legal only for `origin in {driver_path, project}`,
which is what keeps such a driver permanently `trust = local`, unable to reach `inproc` and unable
to satisfy `require_lock = true`.

Read as an `os.pathsep`-separated list, the universal reading of a `*_PATH` variable; the plan
prints "a directory on `OMNIWEAVE_DRIVER_PATH`" and does not spell the separator out.
04-driver-system.md section 4.1."""

PROJECT_DRIVER_DIR: Final[tuple[str, str]] = (".omniweave", "drivers")
"""`.omniweave/drivers/<name>/driver.toml` — a driver vendored into one project, trust `local`.

A tuple of path segments rather than a string, so the join is the platform's and no separator is
hard-coded. Scanned depth-1 from the project root, which arrives as a parameter: `os.getcwd()` and
`Path(".")` are banned in library code (02-architecture.md section 8 clause (e)).
04-driver-system.md section 4.1."""

TOMBSTONE_DIRNAME: Final[str] = "tombstones"
"""`omniweave_core/drivers/tombstones/*.toml`, package data — the framework's own refusals.

Step 5 of `Catalog.build()`, ~1.2 ms for the six files shipped at release 1 (04-driver-system.md
section 4.3). The directory is allowed to be absent and that is not a fault: a source checkout
before the six land, or a wheel built without the package data, gets an empty tombstone set and a
catalog, because discovery never raises."""

DIST_INFO_SUFFIXES: Final[tuple[str, str]] = (".dist-info", ".egg-info")
"""What the validity key stats. `.dist-info` is the measured 1.01 ms case (04-driver-system.md
section 4.3); `.egg-info` is here because a legacy install still declares entry points and a
validity key blind to it would serve a stale card for one."""

PACKAGE_PATH_RE: Final = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)*$")
"""The entry-point VALUE's grammar: a **colon-free dotted package path**.

**Two names, two grammars, and they are not the same name.** This is the entry-point value, which
`setuptools._entry_points.validate` raises at build time on a path-shaped spelling of; discovery
reads it and never imports it. The card's own `[driver] entrypoint` key is `<dotted.module>:<Attr>`
and is matched by `card.ENTRYPOINT_RE` — `activate()` is the only site in the framework that
resolves the colon form, because it must assert the loaded *class's* `PORT` and `SCHEMA_VERSION`
and a package has no such attributes (04-driver-system.md section 4.1, DR2, section 5 C12).

The plan names the two rejections — a value containing `:` or `/` — and this pattern is stricter
than either, on purpose. `card_relative_path()` maps `.` to `/` before the join, so a value with an
empty segment becomes a doubled slash. Leading, `Path(parent) / "//driver.toml"` is an **absolute**
path and the join escapes the distribution entirely; interior, `pathlib` silently collapses it, so
`"a..b"` would locate the card of the package `a.b` for a value nobody wrote. Requiring every
segment to be a Python identifier removes both without needing a second, subtler rule."""

DISCOVERY_CEILING_MS: Final[int] = 250
"""The hard ceiling on `Catalog.build()`, any environment (04-driver-system.md section 4.4).

Crossing it records `DiscoveryDegradation(kind="discovery_slow")` naming the slowest step and the
installed-distribution count. **It is not a failure**: a user with 900 installed distributions gets
a slow catalog and a report, not a refusal. The budget ladder above it — 20 ms at 20 installed
distributions, 45 ms cold and 25 ms warm at 328 — is `tools/gate_coldstart.py`'s to assert, not
this module's to enforce; a library that refused above its own budget would turn a performance
regression into an outage.

That gate carries the same number as `HARD_CEILING_MS`, and the duplication is deliberate rather
than an INV-21 breach: section 4.4's row is the single home and both constants are transcriptions
of it. A gate that read its expected ceiling out of the module it measures would assert only that
the module agrees with itself."""

TIMED_STEPS: Final[tuple[str, ...]] = (
    "entry_points",
    "validity_key",
    "driver_path",
    "project",
    "tombstones",
    "cards",
)
"""The six steps `discover()` times, named so `discovery_slow` can say which one was slowest.

These are steps 1-7 of 04-driver-system.md section 4.3's nine-row table, with 6 and 7 (per-card
cache hit and miss) folded into `cards` because a caller cannot act on the split. Step 8 (the
probe verdict cache) and step 9 (`catalog_digest`) are absent because they belong to
`omniweave_core.drivers.catalog`, not here.

**Not `tools/gate_coldstart.py`'s `DISCOVERY_STEPS`**, which is a different fact under a name
close enough to be worth separating: that one is the nine rows with their *measured costs* on the
reference machine, transcribed so the gate can print the arithmetic. This one is the phase names
this implementation actually times. A gate that read its expected costs out of the module it
checks would check nothing, so the two are deliberately independent."""

DISCOVERY_DEGRADATION_KINDS: Final[frozenset[str]] = frozenset(
    {"discovery_slow", "driver_unavailable"}
)
"""The two `DegradationKind` members discovery can record, and there is no third.

Both are real members of 15-observability.md section 6.3's closed twenty-seven-member literal —
`discovery_slow` is row 9 and `driver_unavailable` is row 3 — so this set is a *subset* of that
vocabulary and never a widening of it. `DiscoveryDegradation` validates against it in
`__post_init__`, which is what stops this module minting a twenty-eighth member by typo."""

_CARD_INVALID: Final[str] = "OW_CARD_INVALID"
_CARD_CHECK_FIX: Final[str] = f"ow drivers check <path/to/{CARD_FILENAME}>"


# --------------------------------------------------------------------------------------------
# 2. The records. Every one of these is carried, never raised.
# --------------------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class EntryPointRef:
    """One `name = value` row of an entry-point group, read without importing anything.

    Carried for `TARGET_GROUP` and `BACKEND_GROUP`, whose values name a package but not a card:
    an artefact alias and a `VectorBackend` respectively. `CardSource` is the driver-group
    counterpart and carries the located path as well (04-driver-system.md section 4.1).
    """

    group: str
    name: str
    value: str
    dist_name: str
    dist_version: str


@dataclass(frozen=True, slots=True)
class CardSource:
    """Where one card was found, before anything has been read. Discovery's own fact.

    `origin` is not a card field and never can be: a card that could name its own origin could
    name its own trust, and `origin` is exactly what `[driver] exec` is gated on and what
    `trust` (E13, section 4.2) is later computed from. `load_card()` takes it as a keyword for
    the same reason.

    `card_path` is the cache key's fourth column and is deliberately **relative** for an
    `entry_point` — `omniweave_driver_ipynb/driver.toml` — because the other three columns
    already pin the distribution, and an absolute path would make the row miss after the venv
    moved. For `driver_path`, `project` and `tombstone` there is no distribution, so the
    absolute path is the only thing that identifies the row.
    """

    origin: CardOrigin
    path: Path
    card_path: str
    dist_name: str = ""
    dist_version: str = ""
    declared_id: str | None = None
    editable: bool = False


@dataclass(frozen=True, slots=True)
class DiscoveryFault:
    """A card discovery refused, **recorded and not raised** (04-driver-system.md section 4.5).

    "Discovery never raises; a broken neighbour cannot stop a catalog" is the whole reason this
    type exists. `symbol` is the `codes.toml` symbol the equivalent `DriverHostError` would have
    carried, so `ow drivers check` and `ow doctor` print the same code whether the card was
    refused during discovery or during a direct check.

    `detail` is machine-readable where the plan names a detail (`card_missing`) and is the
    loader's own message otherwise, because that message already names the key and the cap.
    """

    symbol: str
    detail: str
    source: str
    origin: CardOrigin
    fix: str
    dist_name: str = ""


@dataclass(frozen=True, slots=True)
class DiscoveryDegradation:
    """A downgrade discovery records. One of `DISCOVERY_DEGRADATION_KINDS`.

    **This is a placeholder for `omniweave_core.observe.degradation.Degradation`**, which
    15-observability.md section 6.3 is the sole home of (charter erratum E15) and which has not
    landed: `observe` is not one of the eight subpackage homes P1 creates. The two kinds this
    module records are genuine members of that module's closed twenty-seven-member literal, so
    the substitution is a missing *type*, not an invented *vocabulary*. The field names are
    section 6.3's, so the eventual swap is a rename of the class and nothing else.

    `message` MUST name the knob or the command that undoes the downgrade, in prose; `knob` and
    `fix_command` carry the same fact machine-readably. `knob = None` is a positive assertion —
    no configuration change raises this — and both of discovery's members are that: a missing
    card is fixed by reinstalling the distribution, and a slow catalog is fixed by installing
    fewer things.
    """

    kind: str
    message: str
    wanted_driver: str | None = None
    knob: str | None = None
    fix_command: str | None = None

    def __post_init__(self) -> None:
        if self.kind not in DISCOVERY_DEGRADATION_KINDS:
            raise ValueError(
                f"{self.kind!r} is not one of discovery's two DegradationKind members "
                f"{sorted(DISCOVERY_DEGRADATION_KINDS)}; the closed literal is "
                f"15-observability.md section 6.3's and this module may not widen it"
            )
        if not self.message:
            raise ValueError("a Degradation carries one sentence naming the knob or the command")


@dataclass(frozen=True, slots=True)
class DiscoveredCard:
    """One loaded card paired with where it came from.

    A pair rather than a mapping keyed on id, because **two distributions may declare the same
    id** and that is `Registry.register`'s `DuplicateDriver` to raise and `resolve()`'s
    `ID_COLLISION_UNQUALIFIED` to report (04-driver-system.md section 4.5). A dict here would
    drop one of the two silently, which is the exact failure DataFlow supplies the receipt for:
    a registry keyed on a bare `__name__`, first-wins and silent, so two plugins with one class
    name means one vanishes with no diagnostic.
    """

    card: DriverCard | Tombstone
    source: CardSource
    cached: bool = False


@dataclass(frozen=True, slots=True)
class LoadOutcome:
    """What `load_one()` produced: at most one card, at most one fault, at most one degradation.

    Three optional fields rather than a union, because `card_missing` produces a fault **and** a
    degradation from one attempt, and because a caller accumulating a catalog wants to extend
    three lists without re-deciding which arm it took.
    """

    found: DiscoveredCard | None = None
    fault: DiscoveryFault | None = None
    degradation: DiscoveryDegradation | None = None


@dataclass(frozen=True, slots=True)
class Discovery:
    """Everything one pass over the machine found. The input `Catalog.build()` assembles.

    Not a `Catalog`: there is no `catalog_digest` and no `probe_status` here, because both belong
    to `omniweave_core.drivers.catalog` (04-driver-system.md section 4.7) and because a digest
    over rows this module has not de-duplicated would be a digest over a registry that does not
    exist yet.

    `validity_key` is the wholesale cache key of section 4.3 — sha256 over the sorted
    `(dist-info path, mtime_ns, size)` triples — and a caller stores it beside the catalog so the
    next run can pass it back as `cached_validity_key`.
    """

    found: tuple[DiscoveredCard, ...] = ()
    targets: tuple[EntryPointRef, ...] = ()
    backends: tuple[EntryPointRef, ...] = ()
    faults: tuple[DiscoveryFault, ...] = ()
    degradations: tuple[DiscoveryDegradation, ...] = ()
    validity_key: str = ""
    distributions: int = 0
    elapsed_ms: Mapping[str, float] = field(default_factory=lambda: MappingProxyType({}))

    @property
    def cards(self) -> tuple[DriverCard, ...]:
        """The driver cards, tombstones excluded."""
        return tuple(f.card for f in self.found if isinstance(f.card, DriverCard))

    @property
    def tombstones(self) -> tuple[Tombstone, ...]:
        """The framework's refusals, driver cards excluded."""
        return tuple(f.card for f in self.found if isinstance(f.card, Tombstone))

    @property
    def total_ms(self) -> float:
        """Wall time across all six steps — what `DISCOVERY_CEILING_MS` is compared against."""
        return sum(self.elapsed_ms.values())


# --------------------------------------------------------------------------------------------
# 3. The card cache. `driver_card_cache` in the store; a Protocol here.
# --------------------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class CardCacheRow:
    """One `driver_card_cache` row: the four key columns, the two validity columns, two payloads.

    The table is keyed `(prefix, dist_name, dist_version, card_path)` and validated on
    `(mtime_ns, size)` (04-driver-system.md section 4.3). Its DDL "belongs to 08-runtime.md",
    which does not print it — the eight columns here are the superseded charter's, transcribed
    so the eventual DDL and this record agree.

    `prefix` is given no meaning anywhere in the plan. It is the **origin** here — one of
    `card.CARD_ORIGINS` — because that is the only value that disambiguates the other three
    columns: a `driver_path` card has no distribution, so its `dist_name` and `dist_version` are
    empty and two origins could otherwise collide on one absolute path.

    `card_json` holds `json.dumps(<the card's UTF-8 source text>)`. Section 4.3 prices a cache
    hit at `json.loads(driver_card_cache.card_json)` and ~0.05 ms, which is a hit that
    reconstructs a `DriverCard` from a *document* without re-validating — and `load_card()` is
    the only constructor of `DriverCard` and takes bytes. So P1's hit skips the `locate_file` and
    the disk read but still pays `tomllib` plus validation, ~0.35 ms; closing that gap needs a
    document-level constructor in `omniweave_core.drivers.card`, which this module may not add.

    `card_sha256` is stored so a hit can be cross-checked against the digest `load_card()`
    recomputes. A mismatch means the row is corrupt, and a corrupt row is treated as a miss
    rather than trusted: a cache that can silently serve the wrong bytes for a `card_sha256` in
    the lockfile is worse than no cache.
    """

    prefix: str
    dist_name: str
    dist_version: str
    card_path: str
    mtime_ns: int
    size: int
    card_json: str
    card_sha256: str

    @property
    def key(self) -> tuple[str, str, str, str]:
        """The primary key, as a tuple, for a dict-backed implementation."""
        return (self.prefix, self.dist_name, self.dist_version, self.card_path)

    @property
    def text(self) -> str:
        """The card's source text — `json.loads(card_json)`, section 4.3's hit-path expression."""
        decoded = json.loads(self.card_json)
        if not isinstance(decoded, str):
            raise TypeError(f"card_json for {self.key} is a {type(decoded).__name__}, not a str")
        return decoded

    @classmethod
    def of(
        cls,
        source: CardSource,
        *,
        raw: bytes,
        mtime_ns: int,
        size: int,
        digest: str,
    ) -> CardCacheRow:
        """Build the row a miss writes back. `raw` is the bytes `load_card()` accepted."""
        return cls(
            prefix=source.origin,
            dist_name=source.dist_name,
            dist_version=source.dist_version,
            card_path=source.card_path,
            mtime_ns=mtime_ns,
            size=size,
            card_json=json.dumps(raw.decode("utf-8")),
            card_sha256=digest,
        )


class CardCache(Protocol):
    """The two operations discovery needs of `driver_card_cache`, and no more.

    A Protocol rather than an import, because `sqlite3` is banned outside `omniweave_core/store/`
    (INV-17) and discovery is not there. The runtime hands in the store-backed implementation;
    `MemoryCardCache` is the in-process default for a run with no store and the double every
    test in this cluster uses.

    Writes are idempotent per `(prefix, dist_name, dist_version, card_path)` and last-writer-wins
    on equal content (04-driver-system.md section 9's operational table), so `put()` is an upsert
    and never a conflict.
    """

    def get(self, key: tuple[str, str, str, str]) -> CardCacheRow | None:
        """The row for that key, or `None`. Never raises: a cache miss is not a failure."""
        ...

    def put(self, row: CardCacheRow) -> None:
        """Upsert. Never raises for a reason a caller could act on."""
        ...


class MemoryCardCache:
    """A dict-backed `CardCache`. The no-store default and the test double.

    It is not a performance shortcut — a process-local cache cannot survive the process, which is
    the whole point of `driver_card_cache` — but it does make one `Catalog.build()` per run
    idempotent, and it lets the hit and miss paths be tested without a database.
    """

    __slots__ = ("_rows",)

    def __init__(self, rows: Iterable[CardCacheRow] = ()) -> None:
        self._rows: dict[tuple[str, str, str, str], CardCacheRow] = {row.key: row for row in rows}

    def get(self, key: tuple[str, str, str, str]) -> CardCacheRow | None:
        return self._rows.get(key)

    def put(self, row: CardCacheRow) -> None:
        self._rows[row.key] = row

    def __len__(self) -> int:
        return len(self._rows)


# --------------------------------------------------------------------------------------------
# 4. The entry-point value: read, never imported.
# --------------------------------------------------------------------------------------------


def card_relative_path(value: str) -> str:
    """`"omniweave_driver_ipynb"` -> `"omniweave_driver_ipynb/driver.toml"`.

    04-driver-system.md section 4.1 prints the expression verbatim:
    `Distribution.locate_file(value.replace(".", "/") + "/driver.toml")`. Forward slashes even on
    Windows, because `locate_file` joins through `pathlib`, which accepts them on every platform.

    The caller must have validated `value` against `PACKAGE_PATH_RE` first — this function is the
    join and performs no checking, so that the check has exactly one home.
    """
    return value.replace(".", "/") + "/" + CARD_FILENAME


def entry_point_value_fault(ref: EntryPointRef) -> DiscoveryFault | None:
    """`None` if the entry-point value is a legal colon-free dotted package path, else the fault.

    The two spellings the plan names are called out by name in the message, because they are the
    two a developer actually writes: a `:` is the card's `entrypoint` grammar pasted into the
    wrong field, and a `/` is a path where a package was wanted. `setuptools._entry_points.validate`
    already raises at build time on the path-shaped form, so reaching this in a wheel means the
    wheel was not built by setuptools — which is exactly when a defence in depth is worth having.

    The fault carries `OW_CARD_INVALID` because the plan allocates no numeric of its own for a
    malformed entry-point *value*: `OW_CARD_ENTRYPOINT_MALFORMED` (OW-D-011) is explicitly the
    card's `[driver] entrypoint` key and `codes.toml` says so in its `meaning`. A value that
    cannot name a package cannot name a card, so the card is invalid by absence.
    """
    if PACKAGE_PATH_RE.match(ref.value):
        return None
    if ":" in ref.value:
        why = "it contains ':', which is the CARD's `entrypoint` grammar, not this one"
    elif "/" in ref.value or "\\" in ref.value:
        why = "it contains a path separator; the value names a package, never a file"
    else:
        why = "it is not a dotted path of Python identifiers"
    return DiscoveryFault(
        symbol=_CARD_INVALID,
        detail="entry_point_value_malformed",
        source=f'[{ref.group}] "{ref.name}" = "{ref.value}" -- {why}',
        origin="entry_point",
        fix=f'fix [project.entry-points."{ref.group}"] in {ref.dist_name or "the distribution"}',
        dist_name=ref.dist_name,
    )


def entry_point_refs(
    distributions: Iterable[Distribution],
    *,
    groups: Sequence[str] = (DRIVER_GROUP, TARGET_GROUP, BACKEND_GROUP),
) -> dict[str, list[EntryPointRef]]:
    """Every `name = value` row of `groups`, per group, with **no `EntryPoint.load()`**.

    Reads `Distribution.entry_points`, which parses `entry_points.txt` and nothing else. The
    value is carried as the string it is; resolving it is `activate()`'s and only for the card's
    own colon-bearing `entrypoint`, never for this one (04-driver-system.md section 4.6).

    `OPERATOR_GROUP` is absent from the default and that is the reservation being kept: a group
    that quietly began working would make "reserved and uncreated" untrue.
    """
    wanted = set(groups)
    refs: dict[str, list[EntryPointRef]] = {group: [] for group in groups}
    for dist in distributions:
        name = _dist_name(dist)
        version = _dist_version(dist)
        for entry in dist.entry_points:
            if entry.group in wanted:
                refs[entry.group].append(
                    EntryPointRef(
                        group=entry.group,
                        name=entry.name,
                        value=entry.value,
                        dist_name=name,
                        dist_version=version,
                    )
                )
    return refs


def entry_point_sources(
    distributions: Iterable[Distribution],
) -> tuple[tuple[CardSource, ...], tuple[DiscoveryFault, ...]]:
    """Locate one card per legal `DRIVER_GROUP` row; one fault per illegal entry-point value.

    The card is located by NAME — `Distribution.locate_file(card_relative_path(value))` — and
    never by walking `Distribution.files`: that scan was measured at **2124 ms** for 328
    installed distributions against a claimed 1-4 ms, three orders of magnitude wrong on the
    discovery path (04-driver-system.md section 4.1).

    Existence is not checked here. A located path that is missing is section 4.5's first named
    failure mode and is `load_one()`'s to report, as a `card_missing` fault plus one
    `driver_unavailable` degradation — stat'ing twice would price the same syscall twice on the
    path INV-3 holds to 80 ms.
    """
    dists = list(distributions)
    return _driver_group_sources(dists, {id(dist): is_editable(dist) for dist in dists})


EDITABLE_LAYOUTS: Final[tuple[str, ...]] = ("src", "")
"""Where an editable distribution's package can sit under its project directory. D128's ruling.

`uv sync` installs every workspace member editable: `site-packages` holds a `.pth` pointing at
`<project>/src` and no package directory, so `Distribution.locate_file()` resolves a card to a path
that does not exist and the catalog comes back EMPTY on every checkout (measured: `cards []`).

The user chose, in W7.3y, D128's first option with both layouts checked: `direct_url.json`'s
`"url"` names the project directory (`"dir_info": {"editable": true}` is what marks the install),
and the file is looked for at `<project>/src/<relative>` and `<project>/<relative>`. The layout is
**stat'ed, not guessed** -- the objection D128 recorded against the first option was that
`dist-info` does not record `src/` versus flat -- and a project holding both is refused, because
two cards for one entry point is a choice nothing here may make. No import machinery is used, so
INV-4 is untouched, and a non-editable distribution takes `locate_file()` exactly as before.
"""


_DRIVE_PREFIX: Final[int] = 2


class EditableLayoutAmbiguousError(ValueError):
    """An editable project holds the file under both layouts. Raised, reported by the caller."""


def locate_package_file(dist: Distribution, relative: str) -> Path:
    """`relative` inside `dist`'s package: `locate_file()`, or the editable project's copy. D128.

    Returns the `locate_file()` path whenever the editable branch finds nothing, so the caller's
    existing missing-file report (`card_missing`, a signals `missing` row) still names the path
    that was expected. Raises `EditableLayoutAmbiguousError` when both layouts hold the file.
    """
    located = Path(str(dist.locate_file(relative)))
    if not is_editable(dist):
        return located
    project = _editable_project(dist)
    if project is None:
        return located
    found = [
        candidate
        for candidate in (
            project / layout / relative if layout else project / relative
            for layout in EDITABLE_LAYOUTS
        )
        if candidate.is_file()
    ]
    if len(found) > 1:
        raise EditableLayoutAmbiguousError(
            f"{relative} exists under both {found[0]} and {found[1]}; an editable project may "
            f"hold one"
        )
    return found[0] if found else located


def _editable_project(dist: Distribution) -> Path | None:
    """The project directory `direct_url.json` names, or `None` for any other URL."""
    try:
        raw = dist.read_text("direct_url.json")
        parsed = json.loads(raw) if raw else None
    except (OSError, json.JSONDecodeError):
        return None
    url = parsed.get("url") if isinstance(parsed, dict) else None
    if not isinstance(url, str) or not url.startswith("file:"):
        return None
    parts = urlsplit(url)
    path = unquote(parts.path)
    #  `file:///E:/a` -> `/E:/a`: a drive letter keeps no leading slash. `url2pathname` does this
    #  and lives in `urllib.request`, which can dial and which G15 refuses in core for one join.
    if len(path) > _DRIVE_PREFIX and path[0] == "/" and path[2] == ":" and path[1].isalpha():
        path = path[1:]
    return Path(f"//{parts.netloc}{path}" if parts.netloc else path)


def is_editable(dist: Distribution) -> bool:
    """True when this distribution's `dist-info` says `"editable": true`.

    Section 4.3: "The wholesale key has one blind spot and it is the developer's own workflow."
    The validity key stats `*.dist-info`, and `uv pip install -e .` leaves `dist-info` untouched
    while the author edits `driver.toml` in the source tree — so a wholesale-valid cache would
    serve the *old* card through the entire edit-conform-fix loop. An editable distribution is
    therefore **always** stat'ed per card, wholesale key or not. Cost: one `stat` per editable
    distribution, which in practice is one.

    `Distribution.read_text` is used rather than a path join because it is the public reader for
    a `dist-info` sibling file and works for every `Distribution` subclass. A distribution
    reached through a `.pth` rather than a `direct_url.json` is **not** detected here; that half
    is unimplemented and the consequence is bounded — it is only reachable when a caller opts
    into `cached_validity_key`, and `discover()` stats per card by default.
    """
    try:
        raw = dist.read_text("direct_url.json")
    except OSError:
        return False
    if not raw:
        return False
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return False
    if not isinstance(parsed, dict):
        return False
    dir_info = parsed.get("dir_info")
    return isinstance(dir_info, dict) and dir_info.get("editable") is True


def _dist_name(dist: Distribution) -> str:
    """The distribution's name, or `""` when its metadata is unreadable.

    An unreadable `METADATA` is a broken neighbour, and section 4.5's rule is that a broken
    neighbour cannot stop a catalog. The empty name is honest: it makes the cache row for that
    distribution collide with nothing and it prints as an obviously wrong value in a report.
    """
    try:
        return dist.metadata["Name"] or ""
    except (OSError, KeyError):  # pragma: no cover - a torn dist-info on the reference machine
        return ""


def _dist_version(dist: Distribution) -> str:
    """The distribution's version, or `""`. Same reasoning as `_dist_name`."""
    try:
        return dist.version or ""
    except (OSError, KeyError):  # pragma: no cover - a torn dist-info on the reference machine
        return ""


# --------------------------------------------------------------------------------------------
# 5. The three directory scans. Depth 1, never recursive.
# --------------------------------------------------------------------------------------------


def _depth_one_cards(root: Path, origin: CardOrigin) -> list[CardSource]:
    """`<root>/*/driver.toml`, one level down and no further.

    Depth-1 and not a walk, for two reasons the plan gives directly: the cost budget prices this
    at ~0.1 ms per directory (section 4.3 steps 3 and 4), and `*/driver.toml` is the printed
    pattern (section 4.1). A recursive walk over a development tree would find the `driver.toml`
    inside a nested `.venv`, a `build/` directory or a vendored checkout — three copies of one
    card, at three different paths, with no way to tell which the author meant.

    A `driver.toml` sitting directly in `root` is deliberately NOT picked up: the pattern has a
    directory component, and that directory's name is what a `driver_path` entry is identified
    by in a report.
    """
    found: list[CardSource] = []
    try:
        with os.scandir(root) as entries:
            children = sorted(entries, key=lambda e: e.name)
    except OSError:
        return found
    for entry in children:
        if not entry.is_dir():
            continue
        card = Path(entry.path) / CARD_FILENAME
        if card.is_file():
            found.append(CardSource(origin=origin, path=card, card_path=str(card)))
    return found


def driver_path_sources(env: Mapping[str, str] | None = None) -> tuple[CardSource, ...]:
    """Every `<dir>/*/driver.toml` on `OMNIWEAVE_DRIVER_PATH`, in the order the variable lists.

    `env` is a parameter and not `os.environ`, because the environment is one of the ambient
    inputs 02-architecture.md section 8 clause (e) makes a caller declare: a function that reads
    the process environment cannot be varied by a test and behaves differently under `ow serve`
    than under `ow ingest`. `None` means "no environment was declared", which yields nothing —
    an honest empty answer rather than a silent read of the real one.

    Order is preserved so an operator can shadow a card by listing its directory first; discovery
    reports both and `Registry` decides, because two cards with one id is `DuplicateDriver`'s to
    raise and not this function's to resolve (04-driver-system.md sections 4.1 and 4.5).
    """
    raw = (env or {}).get(DRIVER_PATH_ENV, "")
    sources: list[CardSource] = []
    for part in raw.split(os.pathsep):
        directory = part.strip()
        if directory:
            sources.extend(_depth_one_cards(Path(directory), "driver_path"))
    return tuple(sources)


def project_sources(project_root: Path | None) -> tuple[CardSource, ...]:
    """`.omniweave/drivers/<name>/driver.toml` under `project_root` — a driver vendored into one
    project, trust `local` (04-driver-system.md section 4.1).

    `project_root` is a parameter and `None` is legal, for the reason `driver_path_sources` takes
    an `env`: `os.getcwd()` and `Path(".")` are banned in library code by
    `tools/semgrep/omniweave.yaml`, because a relative root resolves against whatever directory
    the process happens to be in — graphify #1774 wrote its cache into the analysed tree that
    way. The runtime injects `Roots`; a caller with no project passes `None` and gets nothing.
    """
    if project_root is None:
        return ()
    return tuple(_depth_one_cards(project_root.joinpath(*PROJECT_DRIVER_DIR), "project"))


def tombstone_sources(directory: Path | None = None) -> tuple[CardSource, ...]:
    """`omniweave_core/drivers/tombstones/*.toml`, package data — step 5, ~1.2 ms for six files.

    Every `*.toml` in the directory, not `driver.toml`: a tombstone is one file per refused
    driver and its name is the refused id, so the six shipped at release 1 are six files
    (04-driver-system.md sections 4.3 and 7.5).

    The default is resolved from this module's own location rather than passed in, because it is
    package data this distribution owns rather than an input a caller could sensibly vary — and
    an absent directory returns `()` rather than raising, because a source checkout before the
    six land still has to be able to build a catalog.
    """
    root = directory if directory is not None else _shipped_tombstone_dir()
    try:
        with os.scandir(root) as entries:
            files = sorted(entries, key=lambda e: e.name)
    except OSError:
        return ()
    return tuple(
        CardSource(origin="tombstone", path=Path(entry.path), card_path=str(Path(entry.path)))
        for entry in files
        if entry.is_file() and entry.name.endswith(".toml")
    )


def _shipped_tombstone_dir() -> Path:
    """`<this package>/drivers/tombstones`. Derived from `__file__`, never from the cwd."""
    return Path(__file__).resolve().parent / "drivers" / TOMBSTONE_DIRNAME


# --------------------------------------------------------------------------------------------
# 6. The wholesale validity key. 1.01 ms for 328 distributions; a RECORD scan is 2124 ms.
# --------------------------------------------------------------------------------------------


def dist_info_triples(search_path: Sequence[str] | None = None) -> list[tuple[str, int, int]]:
    """The `(dist-info path, mtime_ns, size)` triples the wholesale validity key digests.

    **This is the measurement that decides the cache's whole design.** `os.scandir` + `stat` of
    every `*.dist-info` costs **1.01 ms** for 328 installed distributions on the reference machine
    (Windows / 3.11.9, warm), which is why the card cache is validated *wholesale* rather than
    once per card, and it is three orders of magnitude cheaper than the **2124 ms** `RECORD` scan
    that section 4.1 forbids (04-driver-system.md sections 4.1 and 4.3; 12-performance.md's
    measured table).

    `entry.stat()` on a `DirEntry` rather than `Path.stat()`, because `os.scandir` already carries
    the result on Windows and caches it on POSIX — which is what makes 1.01 ms 1.01 ms.

    `search_path` defaults to `sys.path` because there is no other enumeration of install roots;
    it is a parameter so a test can name exactly one directory, and so a caller with a non-default
    finder can pass what that finder searches. A root that does not exist is skipped rather than
    being an error — `sys.path` routinely carries several — and a repeated root is visited once,
    because a duplicated `sys.path` entry must not make one distribution count twice.

    The triple is `(path, mtime_ns, size)` and not the path alone: a wheel reinstalled at the same
    version moves `mtime_ns`, and a key blind to that would serve a stale roster.
    """
    roots = list(sys.path) if search_path is None else list(search_path)
    triples: list[tuple[str, int, int]] = []
    seen: set[str] = set()
    for root in roots:
        if not root or root in seen:
            continue
        seen.add(root)
        try:
            with os.scandir(root) as entries:
                for entry in entries:
                    if entry.name.endswith(DIST_INFO_SUFFIXES):
                        stat = entry.stat()
                        triples.append((entry.path, stat.st_mtime_ns, stat.st_size))
        except OSError:
            continue
    return triples


def validity_key(search_path: Sequence[str] | None = None) -> str:
    """The wholesale card-cache key: 64 bare hex over the sorted `dist_info_triples()`.

    The digest itself is `omniweave_core.drivers.catalog.compute_validity_key`, which is that
    fact's one home (INV-21) and which `Catalog.assemble()` validates its argument against. This
    module owns the **I/O** — which roots are scanned, which entries count, and what a triple is —
    and the catalog module owns the **digest**. Re-implementing the hash here would put one key
    under two recipes, and the two would drift on the first person who reformatted either.

    It is re-checked at run start and at no other time. "One `Catalog` per run, and it is never
    rebuilt mid-run": a catalog that changed under a plan would make `resolution_digest` a lie and
    would let two units of one run be parsed by different drivers with no record of why
    (04-driver-system.md section 4.3).
    """
    return compute_validity_key(dist_info_triples(search_path))


# --------------------------------------------------------------------------------------------
# 7. Loading one card. The three non-cap failure modes of section 4.5 are all here.
# --------------------------------------------------------------------------------------------


def load_one(
    source: CardSource,
    *,
    cache: CardCache | None = None,
    trust_cache: bool = False,
) -> LoadOutcome:
    """Read, validate and return one card. **Never raises for anything a card can contain.**

    The order is: stat (skipped only on a trusted wholesale key for a non-editable
    distribution) -> cache lookup on `(mtime_ns, size)` -> `read_card_bytes()` on a miss ->
    `load_card()` -> write the row back.

    Three outcomes, and each is section 4.5's:

    * **The card is missing or unreadable.** A partially-uninstalled distribution, or a wheel
      built without package data. `OW_CARD_INVALID` with detail `card_missing`, **plus** one
      `DiscoveryDegradation(kind="driver_unavailable")` naming the distribution. Discovery never
      raises; a broken neighbour cannot stop a catalog.
    * **The card is present and invalid.** `load_card()`'s `DriverHostError` is caught and
      recorded with its own symbol and message, so a `OW_CARD_SCHEMA_TOO_NEW` still prints as an
      upgrade instruction rather than as a parse failure.
    * **The card is valid and its `[capability.parse]` disagrees with the code.** Not a load-time
      failure at all — that is the `capability` conformance suite's job, and a card whose
      recomputed `attestation` does not match sets `attested = False` rather than being rejected
      (section 8.3). Nothing here looks for it.

    `read_card_bytes()` performs the bounded `MAX_CARD_BYTES + 1` read at the read boundary, so a
    card bomb is never allocated; `load_card()` then refuses anything over the cap. Both halves
    are `omniweave_core.drivers.card`'s and neither is re-implemented here.

    The `stat` is taken **before** the read, never after, and the direction is load-bearing: a
    file edited between the two then stores current bytes under the previous `(mtime_ns, size)`,
    which the next run re-validates and corrects. The other order stores the NEW stat beside the
    OLD bytes, and the row then validates for the life of the file.
    """
    row = None if cache is None else cache.get(_cache_key(source))
    stat_result = None
    if row is not None and not (trust_cache and not source.editable):
        try:
            stat_result = source.path.stat()
        except OSError as error:
            return _card_missing(source, error)
        if (row.mtime_ns, row.size) != (stat_result.st_mtime_ns, stat_result.st_size):
            row = None

    if row is not None:
        hit = _load_bytes(source, row.text.encode("utf-8"), cached=True)
        if hit.found is not None and hit.found.card.card_sha256 == row.card_sha256:
            return hit
        # A CORRUPT ROW, not a moved card: the key matched, and the payload does not hash to the
        # `card_sha256` stored beside it (or no longer parses at all). Serving it would let the
        # wrong bytes answer for a digest the lockfile pins, so it is dropped and the file is
        # read — and the read overwrites the row, which is why this falls through rather than
        # recursing. A recursive re-read would find the same matching key and loop.

    if cache is not None and stat_result is None:
        # Only the write-back needs the stat, so the cache-less path — `ow drivers check`, and a
        # first run before the store exists — pays one syscall per card rather than two. A
        # missing card is still reported: `read_card_bytes()` raises the same `OSError`.
        try:
            stat_result = source.path.stat()
        except OSError as error:
            return _card_missing(source, error)
    try:
        raw = read_card_bytes(source.path)
    except OSError as error:
        return _card_missing(source, error)

    miss = _load_bytes(source, raw, cached=False)
    if cache is not None and stat_result is not None and miss.found is not None:
        cache.put(
            CardCacheRow.of(
                source,
                raw=raw,
                mtime_ns=stat_result.st_mtime_ns,
                size=stat_result.st_size,
                digest=miss.found.card.card_sha256,
            )
        )
    return miss


def _load_bytes(source: CardSource, raw: bytes, *, cached: bool) -> LoadOutcome:
    """`load_card()` with its refusal turned into a record. The one place that catch lives.

    `DriverHostError` and nothing wider: an `OSError` here would be a defect in this module, and
    `load_card()` is documented never to raise a `ResourceLimit` — a card is a contract and a
    malformed one is refused rather than clamped. The error's own symbol and `fix` are carried
    through unchanged, so a `OW_CARD_SCHEMA_TOO_NEW` still prints as an upgrade instruction.
    """
    try:
        card = load_card(raw, origin=source.origin, source=str(source.path))
    except DriverHostError as error:
        return LoadOutcome(
            fault=DiscoveryFault(
                symbol=error.code(),
                detail=str(error),
                source=str(source.path),
                origin=source.origin,
                fix=error.fix,
                dist_name=source.dist_name,
            )
        )
    return LoadOutcome(found=DiscoveredCard(card=card, source=source, cached=cached))


def _cache_key(source: CardSource) -> tuple[str, str, str, str]:
    """`(prefix, dist_name, dist_version, card_path)` — the `driver_card_cache` primary key."""
    return (source.origin, source.dist_name, source.dist_version, source.card_path)


def _card_missing(source: CardSource, error: OSError) -> LoadOutcome:
    """Section 4.5's first named failure mode: the entry point exists and the card does not.

    A fault AND a degradation from one attempt. The fault carries the detail the plan names,
    `card_missing`, so a report can group these without parsing a message; the degradation names
    the distribution, because "reinstall `omniweave-office`" is the fix and "a card was missing"
    is not.
    """
    who = source.dist_name or str(source.path)
    return LoadOutcome(
        fault=DiscoveryFault(
            symbol=_CARD_INVALID,
            detail="card_missing",
            source=f"{source.path}: {error.strerror or error}",
            origin=source.origin,
            fix=_CARD_CHECK_FIX,
            dist_name=source.dist_name,
        ),
        degradation=DiscoveryDegradation(
            kind="driver_unavailable",
            message=(
                f"{who} declares a driver but ships no readable {CARD_FILENAME}; reinstall the "
                f"distribution — `pip install --force-reinstall {who}` — or remove it from "
                f"[drivers] enabled"
            ),
            wanted_driver=source.declared_id,
            knob=None,
            fix_command=f"pip install --force-reinstall {who}" if source.dist_name else None,
        ),
    )


# --------------------------------------------------------------------------------------------
# 8. One pass over the machine.
# --------------------------------------------------------------------------------------------


def discover(
    *,
    env: Mapping[str, str] | None = None,
    project_root: Path | None = None,
    search_path: Sequence[str] | None = None,
    distributions: Iterable[Distribution] | None = None,
    tombstone_dir: Path | None = None,
    cache: CardCache | None = None,
    cached_validity_key: str | None = None,
    monotonic: Callable[[], float] = time.perf_counter,
) -> Discovery:
    """Steps 1-7 of `Catalog.build()`, once per run. Returns materials, never a `Catalog`.

    Args:
        env: the declared environment. `OMNIWEAVE_DRIVER_PATH` is read from it and from nowhere
            else; `None` means no environment was declared and yields no `driver_path` cards.
        project_root: the root `.omniweave/drivers/` is resolved against. `None` means no
            project. Never defaulted to the cwd — that is banned in library code.
        search_path: install roots for the validity key. Defaults to `sys.path`.
        distributions: the installed distributions. Defaults to `Distribution.discover()`, which
            is `importlib.metadata`'s enumeration over `search_path`. Passed explicitly rather
            than calling `entry_points(group=...)` because the loader needs the `Distribution`
            itself for `locate_file()` — the same scan, priced by section 4.3 at 15.3 ms for 328
            distributions, with the object it already had kept rather than discarded.
        tombstone_dir: overrides the shipped package-data directory. For tests.
        cache: the `driver_card_cache`. `None` disables caching entirely.
        cached_validity_key: the `validity_key` stored beside the previous catalog. When it
            equals this run's, the cache is **wholesale valid** and a non-editable
            distribution's rows are trusted without a per-card `stat`; an editable distribution
            is stat'ed regardless, which is section 4.3's blind spot closed.
        monotonic: the duration clock. Injected because `time.time()` is banned in library code
            and because a test asserting the `discovery_slow` degradation must be able to make
            the catalog slow without actually being slow.

    Order is section 4.3's table: entry points, validity key, `OMNIWEAVE_DRIVER_PATH`, the
    project directory, the framework tombstones, then one load per card. Steps 8 (the probe
    verdict cache) and 9 (`catalog_digest`) are `omniweave_core.drivers.catalog`'s.
    """
    timings: dict[str, float] = {}
    faults: list[DiscoveryFault] = []
    degradations: list[DiscoveryDegradation] = []

    with _timed(timings, "entry_points", monotonic):
        dists = list(Distribution.discover() if distributions is None else distributions)
        refs = entry_point_refs(dists)
        ep_sources, ep_faults = entry_point_sources(dists)
        faults.extend(ep_faults)

    with _timed(timings, "validity_key", monotonic):
        key = validity_key(search_path)

    with _timed(timings, "driver_path", monotonic):
        path_sources = driver_path_sources(env)

    with _timed(timings, "project", monotonic):
        proj_sources = project_sources(project_root)

    with _timed(timings, "tombstones", monotonic):
        tomb_sources = tombstone_sources(tombstone_dir)

    wholesale = cached_validity_key is not None and cached_validity_key == key
    found: list[DiscoveredCard] = []
    with _timed(timings, "cards", monotonic):
        for source in (*ep_sources, *path_sources, *proj_sources, *tomb_sources):
            outcome = load_one(source, cache=cache, trust_cache=wholesale)
            if outcome.found is not None:
                found.append(outcome.found)
            if outcome.fault is not None:
                faults.append(outcome.fault)
            if outcome.degradation is not None:
                degradations.append(outcome.degradation)

    total = sum(timings.values())
    if total > DISCOVERY_CEILING_MS:
        degradations.append(_discovery_slow(timings, total, len(dists)))

    return Discovery(
        found=tuple(found),
        targets=tuple(refs.get(TARGET_GROUP, ())),
        backends=tuple(refs.get(BACKEND_GROUP, ())),
        faults=tuple(faults),
        degradations=tuple(degradations),
        validity_key=key,
        distributions=len(dists),
        elapsed_ms=MappingProxyType(dict(timings)),
    )


def catalog(
    *,
    probe_status: Mapping[str, str] | None = None,
    locked: Mapping[str, str] | None = None,
    manifest: FirstPartyManifest | None = None,
    dist_sha256: Mapping[str, str] | None = None,
    **discovery: object,
) -> Catalog:
    """`discover()` then `Catalog.assemble()` — **discovery's owner interface**.

    02-architecture.md section 2 row 12 fixes this module's owner interface as exactly
    `catalog() -> Catalog`, and `omniweave_core.drivers.catalog.Catalog.build()` calls it by that
    name. It is a thin composition and deliberately so: this module owns every byte of I/O in
    section 4.3's steps, and `catalog.py` owns the checking, the defaulting and the two digests,
    which is what lets the digest properties be tested over adversarial input with no filesystem.

    Args:
        probe_status: verdicts from `$OMNIWEAVE_HOME/probe/` — step 8, which is the runtime's to
            read and not this module's. An id with no entry defaults to `unknown`, which section
            4.7 makes **passing**: an unprobed driver is a candidate, not a refusal.
        locked: `omniweave.lock`'s `[[driver]]` rows as `id -> dist_sha256`. Passed in because
            `resolve()` is pure over `(Requirement, Catalog, Policy)` and the lockfile is loaded
            into `Policy` at startup (section 4.8).
        manifest: the release manifest. `None` reads the shipped one, which every workspace
            checkout lacks — `read_first_party()` returns `None` there and trust falls to row 5.
        dist_sha256: `distribution name -> dist_sha256`, the attestation rows 1-3 of section 4.2's
            trust table compare against. **This module computes none of them**: a distribution
            digest is a hash over installed files, which is the `RECORD` walk section 4.1 forbids
            on the discovery path. Absent, every `entry_point` card computes `unpinned`, which is
            the safe direction — `unpinned` is the tier `require_lock` refuses and the one that
            grants no `inproc`.
        **discovery: forwarded verbatim to `discover()`.

    A **duplicate id** keeps the first card in discovery order — entry points, then
    `OMNIWEAVE_DRIVER_PATH`, then the project directory — and that is a **placeholder, not the
    rule**. Section 4.5 assigns the decision to `Registry.register`, which raises
    `DuplicateDriver` so `resolve()` can emit `ID_COLLISION_UNQUALIFIED` and
    `[drivers.resolve] "<id>" = "<distribution>"` can name the distribution that wins.
    `omniweave_core.registry` is not on disk yet, and `Catalog.cards` is a `Mapping` that
    holds one card per id, so a narrowing has to happen somewhere. It happens **here and not in
    `discover()`**, which returns every discovered card including both halves of a collision — so
    the evidence DataFlow's receipt says must not vanish does not vanish; only this convenience
    wrapper narrows, and it must be replaced by `Registry` when that lands.
    """
    result = discover(**discovery)  # type: ignore[arg-type]
    digests = dist_sha256 or {}
    resolved_manifest = read_first_party() if manifest is None else manifest

    cards: dict[str, DriverCard] = {}
    trust: dict[str, TrustTier] = {}
    for entry in result.found:
        if not isinstance(entry.card, DriverCard):
            continue
        driver_id = entry.card.identity.id
        if driver_id in cards:
            continue
        cards[driver_id] = entry.card
        trust[driver_id] = compute_trust(
            driver_id=driver_id,
            origin=entry.source.origin,
            distribution=entry.source.dist_name,
            dist_sha256=digests.get(entry.source.dist_name, ""),
            manifest=resolved_manifest,
            locked=locked or {},
        ).tier

    return Catalog.assemble(
        validity_key=result.validity_key,
        cards=cards,
        probe_status={k: v for k, v in (probe_status or {}).items() if k in cards},
        trust=trust,
        tombstones=result.tombstones,
    )


def _driver_group_sources(
    dists: Sequence[Distribution],
    editable: Mapping[int, bool],
) -> tuple[tuple[CardSource, ...], tuple[DiscoveryFault, ...]]:
    """One `CardSource` per legal `omniweave.drivers` row, plus a fault per illegal value.

    Cards come from `DRIVER_GROUP` alone. `TARGET_GROUP` aliases the SAME dotted package under
    an artefact kind — `omniweave.targets "pptx" = "omniweave_target_pptx"` beside
    `omniweave.drivers "compile.pptx.native" = "omniweave_target_pptx"` — so locating a card from
    both groups would load one `driver.toml` twice under two different keys (section 4.1). A
    `VectorBackend` in `BACKEND_GROUP` is not a Driver and carries no card at all.
    """
    sources: list[CardSource] = []
    faults: list[DiscoveryFault] = []
    for dist in dists:
        name = _dist_name(dist)
        version = _dist_version(dist)
        for entry in dist.entry_points:
            if entry.group != DRIVER_GROUP:
                continue
            ref = EntryPointRef(
                group=entry.group,
                name=entry.name,
                value=entry.value,
                dist_name=name,
                dist_version=version,
            )
            fault = entry_point_value_fault(ref)
            if fault is not None:
                faults.append(fault)
                continue
            relative = card_relative_path(entry.value)
            try:
                path = locate_package_file(dist, relative)
            except EditableLayoutAmbiguousError as both:
                faults.append(
                    DiscoveryFault(
                        symbol=_CARD_INVALID,
                        detail="editable_layout_ambiguous",
                        source=str(both),
                        origin="entry_point",
                        fix=f"remove one of the two copies in {name or 'the project'}",
                        dist_name=name,
                    )
                )
                continue
            sources.append(
                CardSource(
                    origin="entry_point",
                    path=path,
                    card_path=relative,
                    dist_name=name,
                    dist_version=version,
                    declared_id=entry.name,
                    editable=editable.get(id(dist), False),
                )
            )
    return tuple(sources), tuple(faults)


def _discovery_slow(
    timings: Mapping[str, float],
    total: float,
    installed: int,
) -> DiscoveryDegradation:
    """Crossing 250 ms is a report, not a refusal (04-driver-system.md section 4.4).

    "A user with 900 installed distributions gets a slow catalog and a report, not a refusal."
    The message names the slowest step and the installed-distribution count, which are the two
    facts that distinguish "the environment is large" from "omniweave regressed" — the warm row
    of the budget ladder is dominated by a single `entry_points()` call whose cost is a property
    of the environment rather than of omniweave.

    `knob = None` is a positive assertion: no configuration key raises this ceiling.
    """
    slowest = max(timings, key=lambda step: timings[step]) if timings else "entry_points"
    return DiscoveryDegradation(
        kind="discovery_slow",
        message=(
            f"driver discovery took {total:.0f} ms across {installed} installed distributions, "
            f"over the {DISCOVERY_CEILING_MS} ms ceiling; the slowest step was {slowest!r} at "
            f"{timings.get(slowest, 0.0):.0f} ms — run `ow drivers explain --discovery` for the "
            f"per-step breakdown. No configuration key raises this ceiling; install fewer "
            f"distributions or accept the slower catalog"
        ),
        knob=None,
        fix_command="ow drivers explain --discovery",
    )


class _timed:  # noqa: N801 - a context manager used as a statement reads as a verb, not a class
    """Record one step's wall duration in milliseconds. `__exit__` never swallows.

    A duration and not a wall reading: `time.time()` is banned in library code because a wall
    clock can go backwards and because a determinism harness cannot vary a call that reads the
    machine. The clock is the caller's parameter, which is what lets a test cross
    `DISCOVERY_CEILING_MS` without being slow.
    """

    __slots__ = ("_clock", "_into", "_start", "_step")

    def __init__(self, into: dict[str, float], step: str, clock: Callable[[], float]) -> None:
        self._into = into
        self._step = step
        self._clock = clock
        self._start = 0.0

    def __enter__(self) -> _timed:
        self._start = self._clock()
        return self

    def __exit__(self, *exc: object) -> None:
        self._into[self._step] = (self._clock() - self._start) * 1000.0
