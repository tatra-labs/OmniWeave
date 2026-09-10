"""`resolve()` — the INV-5 gate order, the capability floors, and `RejectCode`.

**W3.1** (16-roadmap.md:481). 02-architecture.md:237 (component row 13) gives the whole contract
in one line — `resolve(Requirement, Catalog, RoutePolicy) -> Resolution`, PURE, memoised, candidates
in ascending `driver_id` order — and 04-driver-system.md section 4.8 gives the gate order that makes
it decidable. This module is both, plus `resolution_report()`, which is the row
`resolution_report.report_json` holds.

**What this module is for.** Discovery produces a *catalog*; a catalog is a list of drivers that
happen to be installed. Turning that into "the drivers that may run this requirement, and a reason
per driver that may not" is the whole job, and INV-5 (01-principles.md:195-218) makes the job
adversarial by design: *installation is not consent*. Every filter below exists because some
installed thing must not run until somebody said so — a licence nobody read, a probe that never
ran, a wheel absent from the lockfile, a driver that crashed three times in the last minute.

## Five properties, each of which is a test

1. **The gate order is observable.** 04-driver-system.md:1340-1360 prints the order and says the
   two filters "the charter's printed list omits" are shown in place. A driver failing several
   gates reports the code of the EARLIEST one, and that code is what `ow drivers explain` prints,
   so the order is part of the contract rather than an implementation detail. `GATE_ORDER` below
   is that order as DATA, walked in sequence by `_first_rejection()`.
2. **`resolve()` never raises and never chooses.** A zero-candidate `Resolution` *is* the error
   message (04:1366-1368): `candidates=()` with a typed `RejectCode` and a detail per considered
   driver, and `len(candidates) + len(rejected) == len(considered)` (DR5). Candidates come back
   sorted on `driver_id` — a canonicalisation forced by `resolution_digest` and **not** a ranking
   (02:280, 04:1371-1375). Ranking is `omniweave.route`'s.
3. **A capability floor is a filter and never a ranking key** (16-roadmap.md:481). `_floor_ok()`
   returns `bool` and has no other return type available to it; nothing in this module sums,
   scores or compares two *candidates* to each other. The comparison semantics differ per field
   and 04-driver-system.md section 2.2 is the definition site: `>=` on an ordered ladder, `⊇` on
   `math`, plain booleans on `text_span`/`marks`/`asset_origin`, and `⊆` **inverted** on
   `forfeits` — the only inverted comparison on the whole card. Comparing a ladder as a boolean,
   or a set with `==`, is the bug the assertion exists for.
4. **`RejectCode` is a typed view over one register.** 04:1443-1447 and 18-api-sketch.md:2162-2166:
   every member has a row in `codes.toml` under `OW-D-nnn`, so the enum is not a second register.
   01-principles.md:605 names "a new `RejectCode` member with no `OW-D-nnn` row" as a defect class
   by name. `RejectCode.symbol` derives the register spelling rather than restating it; see its
   docstring for the one place the plan's stated rule and the register's seeded rows disagree.
5. **`resolve()` is pure and a probe is not.** 04-driver-system.md section 4.7 exists because
   those two facts fight: `resolve()`'s filter order contains "probe verdict not unavailable",
   and `probe()` may import torch. The reconciliation is that **a probe verdict is an INPUT to
   `resolve()`, not an action it takes** — `Catalog.probe_status` carries it, `catalog_digest`
   covers it so a moved verdict invalidates the memo, and `unknown` PASSES the filter because an
   unprobed driver is a candidate and not a refusal. Preflight then probes exactly the candidates
   whose status is `unknown`, out of process, and re-resolves once. Nothing in this module
   imports `omniweave_core.probe`, `omniweave_core.host`, `importlib` or `os`, and a test asserts
   the import set against a pinned literal — which is the assertion that would fail if a probe
   were ever called from inside here.

## Why `Policy` and not `RoutePolicy`

02-architecture.md:237 and :475 name the third argument `RoutePolicy`. That type is
`omniweave.route`'s (05-ingest-and-routing.md:929) and `omniweave_core` may not import
`omniweave` — `tools/layers.toml` gives core exactly `["omniweave_ports"]`. 04-driver-system.md
section 4.8 (:1376-1381) and section 5.3 (:1535) call the argument `Policy`, twice, in the
document that owns the gate order, so `Policy` is the name here. The disagreement is reported
rather than smoothed.

`Policy` is the *frozen* bundle 04:1378-1381 requires: "the ack set, the lockfile id set and the
tombstone digest set are loaded into `Policy` at startup", not read from disk inside `resolve()`,
and `policy_digest` covers all three. Every other field below is there for the same reason — it
is a fact `resolve()` must decide on and may not go and fetch.

## What this module does NOT own: the licence half

`omniweave_core.drivers.licence` (W3.3) owns facts -> tier and text -> ack validity, and its own
docstring assigns the other half here in as many words: "`[licence] allow_tiers`,
`[licence] jurisdiction` and `[licence] fields_of_use` are *selectors* applied by the INV-5 gate
order inside `resolve()` (W3.1)". So gate 11 calls `compute_tier`, `tier_of` and `check_ack` and
computes nothing of its own; `Ack`, `AckSet`, `AckWhich`, `LicenceSeeds` and `TIER_ORDER` are
imported and never restated (INV-21). **There is no tier override on `Policy`**: DR15 is that an
author cannot mislabel a tier, and an operator-supplied tier map would reinstate exactly that
channel one level out from the card.

## Where the memo lives, and why it is not on the `Catalog`

04:1436-1437 asks for an LRU of `RESOLVE_MEMO_MAX = 512` entries "held on the `Catalog` instance
so it dies with the catalog rather than leaking across runs in a served process". `Catalog` is a
frozen slotted dataclass (`drivers/catalog.py`) with no mutable field and no `__weakref__` slot,
so it can carry neither an attribute nor a `weakref.WeakKeyDictionary` entry; both were tried and
both raise. The memo is therefore a bounded module-level LRU keyed on
`(requirement_digest, policy_digest, catalog_digest)` — the three strings 04:1392-1394 specifies,
superseding the charter's stale six-tuple. Because `catalog_digest` is in the key, a dropped
catalog's entries are unreachable rather than merely stale; they are evicted rather than collected,
which is the one behavioural difference and it is bounded at 512 entries of roughly 2 KB.
`resolve_uncached()` is public so a determinism property can be asserted with the memo out of the
way: two equal returns from `resolve()` prove memoisation, not purity.

Specified in 02-architecture.md section 2 row 13 and section 7.4; 04-driver-system.md sections 2.2,
2.3, 4.5, 4.7, 4.8, 5.3, 5.4, 5.5, 6.1 and 7.1-7.3; 01-principles.md INV-5 and DR5;
13-quality.md section 2.4's four memo-key properties; 16-roadmap.md:481.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field, fields, is_dataclass
from enum import StrEnum
from types import MappingProxyType
from typing import Final, NamedTuple

from omniweave_ports.types import (
    ArtifactKind,
    CostClass,
    Isolation,
    LicenceTier,
    Port,
    ProbeEnv,
    Scalar,
    TrustTier,
)

from omniweave_core.canonical import JsonValue, sha256_canonical
from omniweave_core.contract import RELEASE
from omniweave_core.drivers.card import (
    ACQUIRE_AUTHN,
    ACQUIRE_LADDERS,
    CARDS_SUPPORTED,
    DERIVE_ITEMS,
    DERIVE_LADDERS,
    EMBED_INPUTS,
    EMBED_LADDERS,
    EMBED_QUANTIZATIONS,
    GRANULARITIES,
    PARSE_BOOLS,
    PARSE_LADDERS,
    PARSE_SETS,
    DriverCard,
    Tombstone,
)
from omniweave_core.drivers.catalog import Catalog
from omniweave_core.drivers.licence import (
    AckSet,
    AckStatus,
    AckWhich,
    LicenceSeeds,
    check_ack,
    compute_tier,
    tier_of,
)
from omniweave_core.errors import ConfigError

__all__ = [
    "COST_CLASS_ORDER",
    "FLOOR_KINDS",
    "GATE_ORDER",
    "INPROC_TRUST",
    "ISOLATION_CONTAINMENT",
    "PORT_MAJORS_SUPPORTED",
    "RESOLVE_DEGRADATION_KINDS",
    "RESOLVE_MEMO_MAX",
    "Candidate",
    "FloorKind",
    "Gate",
    "MemoStats",
    "Policy",
    "RejectCode",
    "Rejection",
    "Requirement",
    "Resolution",
    "ResolveDegradation",
    "clear_memo",
    "considered_ids",
    "floor_kind",
    "meets_floor",
    "memo_stats",
    "resolution_report",
    "resolve",
    "resolve_uncached",
]

# --------------------------------------------------------------------------------------------
# 1. The closed vocabularies and the four orderings the gates read
# --------------------------------------------------------------------------------------------

PORT_MAJORS_SUPPORTED: Final[frozenset[int]] = frozenset({1})
"""The Port majors this build implements. Gate 1's whole content.

04-driver-system.md:1465 makes the Port major a card declaration bumped by "a core release", and
:1499 makes "adding a method to a Port protocol" a new major with "both majors coexist and
`resolve()` filters on `port major supported`". 16-roadmap.md:494 freezes P3 at "the five Port
protocols at **major 1**", so the set is `{1}`.

**Placing the constant here is our engineering call and not a plan claim.** The plan names no
module for it: 04-driver-system.md:1459 says three framework version axes exist (`RELEASE`,
`CONTRACT`, `SCHEMA`) and "nothing invents a fourth", and `omniweave_core.contract` is by ADR-9 the
sole home of those three and of nothing else. A Port major is a fourth *subordinate* axis whose
only reader is gate 1, so it lives at its one reader rather than acquiring a second home
(INV-21)."""

COST_CLASS_ORDER: Final[tuple[CostClass, ...]] = (
    CostClass.FREE,
    CostClass.LOCAL_COMPUTE,
    CostClass.BILLED_API,
)
"""`free < local_compute < billed_api`, cheapest first — `Requirement.max_cost_class`'s ceiling.

04-driver-system.md:745 prints the domain in that order and 18-api-sketch.md:1646 makes
`billed_api` the opt-in one, so the order is not a house convention: the gate reads
`index(card) <= index(requirement.max_cost_class)`."""

INPROC_TRUST: Final[frozenset[TrustTier]] = frozenset({TrustTier.FIRST_PARTY, TrustTier.VENDORED})
"""`trust in {first_party, vendored}` — the first of DR9's conjuncts (04-driver-system.md:1637).

"No config key widens the first four" (:1645), which is why the isolation gate reads this set and
never a config key."""

ISOLATION_CONTAINMENT: Final[tuple[Isolation, ...]] = (Isolation.INPROC, Isolation.SUBPROC)
"""The isolation modes this build can grant, weakest containment first.

`Isolation` has three members and `wasm` "is in the vocabulary and not built at v1"
(04-driver-system.md:1650), so a card whose `[isolation] requires = "wasm"` is
`ISOLATION_NOT_PERMITTED` rather than silently downgraded: 04:1646 permits the host to *tighten* a
request and this ordering is what "tighten" means — `subproc` contains more than `inproc`."""

RESOLVE_DEGRADATION_KINDS: Final[frozenset[str]] = frozenset({"deprecation", "isolation_shortfall"})
"""The two `DegradationKind` members `resolve()` can record, and there is no third.

Both are real members of 15-observability.md section 6.3's closed twenty-seven-member literal —
`deprecation` is row 11 and `isolation_shortfall` is row 12 — so this is a *subset* of that
vocabulary and never a widening of it, exactly as `omniweave_core.discovery`'s
`DISCOVERY_DEGRADATION_KINDS` is. The `Degradation` **type** is 15-observability.md's sole
property and is not redeclared here (INV-21); `ResolveDegradation` carries the `kind` as a string
the runtime maps."""

RESOLVE_MEMO_MAX: Final = 512
"""The memo's entry ceiling — 04-driver-system.md:1436, with its derivation quoted there.

"The widest shipped configuration is 14 ladder passes plus the parse escalation ladder's rungs
plus one requirement per enabled target — fewer than 128 distinct requirements — and each entry is
a `Resolution` over <= 22 drivers at roughly 2 KB, so the ceiling is about 1 MB." A `MAX_*` this
is not: it is a cache bound, not a limit a producer is built never to exceed (INV-22), which is
why the name has no `MAX_` prefix in the plan and none here."""

_NO_ACKS: Final[AckSet] = AckSet()
_NO_SEEDS: Final[LicenceSeeds] = LicenceSeeds()
"""Empty defaults, as module singletons rather than as calls in a dataclass default.

`omniweave_core.drivers.catalog`'s `_NO_CARDS` sets the precedent: both are frozen and
shareable, and a call in a default is a call every construction pays."""

_SHA256_PREFIX: Final[str] = "sha256:"
"""`resolution_digest`'s prefix, pinned by the plan PRINTING it: 04-driver-system.md:2360 and
:2378 show `resolution_digest sha256:0a37c1be…`. `requirement_digest` and `policy_digest` are bare
hex, because 04:1409's printed recipe ends in `.hexdigest()` and both are cache-key components
rather than values written on a card or in a lockfile (section 2.8)."""


# --------------------------------------------------------------------------------------------
# 2. RejectCode: twenty-six members, one register
# --------------------------------------------------------------------------------------------


class RejectCode(StrEnum):
    """The typed code every `Rejection` carries. **Twenty-six members**, in four refusal points.

    The membership is 04-driver-system.md:1562-1568's table, which is the enumeration and
    therefore the authority. The prose two lines above it (:1557) says "Twenty-five" and its own
    table has twenty-six rows: 3 discovery + 21 resolve (5 identity + 5 fit + 6 policy + 5
    environment) + 1 preflight + 1 activate. The count is reported as a finding; the enumeration
    is what is implemented, and `test_the_reject_code_membership_is_the_plans_own_enumeration`
    re-derives it from the document rather than trusting either number.

    The wire value is "the enum's own wire value (the lower-case member name)" (:1446), which is
    what `resolution_report.report_json` stores and what `ow drivers explain` resolves through
    `codes.toml`.

    Two members are emitted at more than one refusal point and are counted once, at the point
    section 5.3 files them:

    * `CARD_SCHEMA_TOO_NEW` is a **discovery** code (:1522) that gate 6 also emits, because a
      card cached from a newer grammar can reach a catalog that a downgraded core then resolves;
    * `PROBE_UNAVAILABLE` is a **preflight** code (:1541) that gate 15 also emits, because
      section 4.7 makes the verdict an input rather than an action.

    `PORT_MISMATCH` "is the one that reads redundantly next to `PORT_UNSUPPORTED` and is not"
    (:1569): `PORT_UNSUPPORTED` means this core does not implement that Port major at all,
    `PORT_MISMATCH` means the caller asked for `derive/1` and the card is a `parse/1` — a caller
    bug, returned as a rejection rather than raised so a mis-wired policy rule produces a report
    instead of a traceback.
    """

    # -- discovery: no imports (04-driver-system.md:1522-1533, :1562) --------------------------
    CARD_INVALID = "card_invalid"
    CARD_ENTRYPOINT_MALFORMED = "card_entrypoint_malformed"
    CARD_SCHEMA_TOO_NEW = "card_schema_too_new"

    # -- resolve, identity (04-driver-system.md:1563) -------------------------------------------
    PORT_UNSUPPORTED = "port_unsupported"
    PORT_MISMATCH = "port_mismatch"
    ID_COLLISION_UNQUALIFIED = "id_collision_unqualified"
    TOMBSTONED = "tombstoned"
    DEPRECATED_REMOVED = "deprecated_removed"

    # -- resolve, fit (04-driver-system.md:1564) ------------------------------------------------
    FORMAT_UNSUPPORTED = "format_unsupported"
    PRODUCES_INSUFFICIENT = "produces_insufficient"
    CAPABILITY_BELOW_FLOOR = "capability_below_floor"
    GRANULARITY_MISMATCH = "granularity_mismatch"
    NO_WITNESS_SET = "no_witness_set"

    # -- resolve, policy (04-driver-system.md:1565) ---------------------------------------------
    LICENCE_TIER_NOT_ALLOWED = "licence_tier_not_allowed"
    LICENCE_ACK_MISSING = "licence_ack_missing"
    LICENCE_ACK_STALE = "licence_ack_stale"
    COST_CLASS_NOT_PERMITTED = "cost_class_not_permitted"
    NOT_IN_LOCKFILE = "not_in_lockfile"
    UNATTESTED = "unattested"

    # -- resolve, environment (04-driver-system.md:1566) ----------------------------------------
    HARDWARE_ABSENT = "hardware_absent"
    BINARY_ABSENT = "binary_absent"
    ISOLATION_NOT_PERMITTED = "isolation_not_permitted"
    TRUST_INSUFFICIENT = "trust_insufficient"
    QUARANTINED = "quarantined"

    # -- preflight (04-driver-system.md:1567), and activate (04-driver-system.md:1568) ----------
    PROBE_UNAVAILABLE = "probe_unavailable"
    CARD_CODE_MISMATCH = "card_code_mismatch"

    @property
    def symbol(self) -> str:
        """The `codes.toml` symbol this member is a typed view of.

        04-driver-system.md:1444, 18-api-sketch.md:2164 and glossary.md:939 all state the rule as
        `OW_DRIVER_<MEMBER>`. **The register's own seeded rows disagree for the four card
        members**, and the register wins on the four it actually carries: `codes.toml` holds
        `OW-D-010 OW_CARD_INVALID`, `OW-D-011 OW_CARD_ENTRYPOINT_MALFORMED` and
        `OW-D-012 OW_CARD_SCHEMA_TOO_NEW`, each citing 04-driver-system.md:1522-1524 as its
        warrant, and `omniweave_core.drivers.card` raises exactly those three spellings.

        So the derivation is: a member already naming the card carries `OW_` + the member name;
        every other member carries `OW_DRIVER_` + the member name. That reproduces all four rows
        the register has today — the fourth being `OW-D-009 OW_DRIVER_FORMAT_UNSUPPORTED`
        (18-api-sketch.md:2158) — which is what
        `test_every_reject_code_symbol_the_register_already_carries_is_reproduced` asserts. The
        departure from :1444's literal wording is reported rather than hidden, and no numeric is
        invented here: the plan states one, `OW-D-009`, and this module states no others.
        """
        return f"OW_{self.name}" if self.name.startswith("CARD_") else f"OW_DRIVER_{self.name}"


# --------------------------------------------------------------------------------------------
# 3. The value types. DR5 makes a code required to construct a rejection
# --------------------------------------------------------------------------------------------


def _jsonable(value: object) -> JsonValue:
    """Project one field onto `canonical()`'s value grammar.

    04-driver-system.md:1420 states the whole of it: "`_jsonable` sorts a `frozenset` into a list
    and takes `.value` from a `StrEnum`; every other field is already a `Scalar`." Three arms are
    added because `Policy` carries three shapes a `Requirement` does not: a `Mapping`, because
    `Requirement.floors` is one and its values are themselves frozensets; a `Sequence`, because
    `requires_produces` and `Policy.acks` arrive as tuples; and a frozen dataclass, because
    `Policy.host_env` is a `ProbeEnv` and `Policy.acks` holds `Ack` rows. All three recurse
    through this one function, so there is exactly one recipe (INV-21) and a field added to
    `ProbeEnv` or to `Ack` enters `policy_digest` by construction, which is the same property
    04:1415-1425 requires of `Requirement.digest`.
    """
    if isinstance(value, StrEnum):
        return value.value
    if isinstance(value, (frozenset, set)):
        return sorted(_jsonable(member) for member in value)  # type: ignore[type-var]
    if isinstance(value, Mapping):
        return {_json_key(key): _jsonable(item) for key, item in sorted(value.items())}
    if isinstance(value, (tuple, list)):
        return [_jsonable(item) for item in value]
    if isinstance(value, (bool, int, float, str)) or value is None:
        return value
    if is_dataclass(value) and not isinstance(value, type):
        return {f.name: _jsonable(getattr(value, f.name)) for f in fields(value)}
    raise TypeError(f"{type(value).__name__} is not projectable onto canonical JSON")


def _json_key(key: object) -> str:
    """One mapping key as a canonical-JSON key.

    `AckSet.rows` is keyed on `(driver, AckWhich)`, so a bare `str(key)` would put a tuple's
    `repr` -- `AckWhich`'s `<AckWhich.CODE: 'code'>` included -- inside `policy_digest`. The pair
    is joined on `"/"` instead, which is stable under a `StrEnum` whose `__repr__` a future Python
    changes.
    """
    if isinstance(key, tuple):
        return "/".join(_json_key(part) for part in key)
    if isinstance(key, StrEnum):
        return key.value
    return str(key)


def _digest_over_fields(obj: object, *, derived: str) -> str:
    """`sha256(canonical({f.name: _jsonable(getattr(obj, f.name)) for f in fields(obj)}))`.

    **Iterating `dataclasses.fields()` rather than a written-out key list is the mechanism, not a
    stylistic choice** (04-driver-system.md:1415-1425): a ninth field added to `Requirement`
    enters the digest with nobody remembering to add it, which is exactly the property the
    charter's six-tuple lacked and the reason it went stale (ADR-7, R-T15). Narrowing this to an
    enumeration is a regression, and 13-quality.md section 2.4's four property tests exist to
    catch it. The derived digest field itself is excluded by `compare=False`-style convention: it
    is filtered by name, because a field named `digest` cannot be an input to itself.
    """
    body = {
        name: _jsonable(getattr(obj, name))
        for name in (f.name for f in fields(obj))  # type: ignore[arg-type]
        if name != derived
    }
    return sha256_canonical(body)


@dataclass(frozen=True, slots=True)
class Rejection:
    """`(DriverId, RejectCode, detail)` — **returned, never raised** (glossary.md:940).

    **DR5 is a type-level obligation and not a convention**: 01-principles.md:210-212 makes "a
    `Rejection` carrying a typed `RejectCode` required to construct a `Resolution`" the `A`-class
    enforcement of INV-5. So `code` is a required positional argument of the declared type and
    `__post_init__` refuses anything else — a bare `"format_unsupported"` string included, because
    `RejectCode` is a `StrEnum` and `isinstance(str)` would have let the untyped spelling through
    the one check that exists to stop it. `detail` is required and must be non-empty for the same
    reason 18-api-sketch.md:2159 prints one: a rejection that does not name the offending fact is
    a verdict, and the point of the report is to be actionable.

    `gate` records WHICH gate refused, which is what makes the order in 04-driver-system.md:1340
    observable to `ow drivers explain` rather than merely implemented.
    """

    driver_id: str
    code: RejectCode
    detail: str
    gate: str = ""

    def __post_init__(self) -> None:
        if type(self.code) is not RejectCode:
            raise TypeError(
                f"Rejection.code must be a RejectCode member, not "
                f"{type(self.code).__name__} {self.code!r} (DR5, 01-principles.md:210)"
            )
        if not self.driver_id:
            raise ValueError("Rejection.driver_id is required: a rejection names one driver")
        if not self.detail:
            raise ValueError(
                f"Rejection({self.driver_id}, {self.code.value}) has an empty detail: a "
                f"rejection must name the offending fact (18-api-sketch.md:2159)"
            )

    @property
    def symbol(self) -> str:
        """The `codes.toml` symbol, for `ow drivers explain`."""
        return self.code.symbol

    def row(self) -> tuple[str, str, str]:
        """`(driver_id, RejectCode, detail)` as 02-architecture.md:1039 writes the report row."""
        return (self.driver_id, self.code.value, self.detail)


@dataclass(frozen=True, slots=True)
class ResolveDegradation:
    """A degradation `resolve()` records instead of refusing. Two kinds and no third.

    04-driver-system.md:1585 (`since <= RELEASE < removed_in` "records
    `Degradation(kind="deprecation")` naming the replacement and still runs the driver") and
    :1646 (a card asking for `inproc` that fails a conjunct "runs `subproc`
    (`Degradation(kind="isolation_shortfall")`, not a refusal)") each require a carrier, and
    `Resolution` is the only value `resolve()` returns. The `Degradation` type is
    15-observability.md's; this is the local record `omniweave_core.discovery`'s
    `DiscoveryDegradation` already sets the precedent for.
    """

    kind: str
    driver_id: str
    detail: str

    def __post_init__(self) -> None:
        if self.kind not in RESOLVE_DEGRADATION_KINDS:
            raise ValueError(
                f"{self.kind!r} is not one of resolve()'s two DegradationKind members "
                f"{sorted(RESOLVE_DEGRADATION_KINDS)} (15-observability.md section 6.3)"
            )
        if not self.detail:
            raise ValueError(f"ResolveDegradation({self.kind}) must name what degraded")


@dataclass(frozen=True, slots=True)
class Requirement:
    """What a caller needs from a Port. **Eight fields plus the derived digest.**

    The eight are the charter's, unchanged (04-driver-system.md:1404-1406), and the four the
    charter's memo tuple omitted are the four 17-risks.md R-T15 is about: `input_kind`,
    `requires_produces`, `granularity` and `pinned` all change the answer, so two requirements
    differing only in one of them must not collide.

    `format` is a **media type**, not a format token. 04-driver-system.md:1344 gates it as "format
    in `capability.formats`", :445 makes `[capability] formats` the media-type list, :2374 prints
    `resolve(parse/1, format=application/x-ipynb+json)` and 18-api-sketch.md:2158-2159 prints the
    refusal as "`'application/pdf'` is not in `[capability] formats = ["text/plain"]`".
    02-architecture.md:475's worked `Requirement(format='pdf')` is a *token* and is the one site
    that says otherwise; the disagreement is reported and 04 is followed, it being the owning
    document with three sites to 02's one.

    `pinned` is the explicit pin that waives the attestation gate (04-driver-system.md:1356,
    :2101) and, per 13-quality.md:220, "the one field whose whole purpose is reproducibility": it
    carries a `DriverId`, optionally in the `<id>@<dist>` qualified form of :1476.
    """

    port: str
    format: str = ""
    floors: Mapping[str, Scalar | frozenset[str]] = MappingProxyType({})
    max_cost_class: CostClass = CostClass.LOCAL_COMPUTE
    granularity: str | None = None
    input_kind: ArtifactKind | None = None
    requires_produces: frozenset[ArtifactKind] = frozenset()
    pinned: str | None = None
    digest: str = field(init=False, compare=False, repr=False, default="")

    def __post_init__(self) -> None:
        if _PORT_RE.fullmatch(self.port) is None:
            raise ValueError(
                f"Requirement.port {self.port!r} is not <name>/<major> over the five Ports "
                f"(04-driver-system.md:1465)"
            )
        if self.granularity is not None and self.granularity not in GRANULARITIES:
            raise ValueError(
                f"Requirement.granularity {self.granularity!r} is not one of "
                f"{list(GRANULARITIES)} (04-driver-system.md:720)"
            )
        object.__setattr__(self, "digest", _digest_over_fields(self, derived="digest"))

    @property
    def port_name(self) -> Port:
        """The Port the id's first segment is (04-driver-system.md:1474)."""
        return Port(self.port.split("/", 1)[0])

    @property
    def port_major(self) -> int:
        """The integer gate 1 filters on, parsed rather than string-compared."""
        return int(self.port.split("/", 1)[1])


@dataclass(frozen=True, slots=True)
class Policy:
    """The frozen resolve-time bundle. **Everything `resolve()` reads that is not the catalog.**

    04-driver-system.md:1376-1381: "Purity requires that everything it reads is inside those
    three arguments, which has two consequences worth stating because they are easy to get wrong:
    **the ack set, the lockfile id set and the tombstone digest set are loaded into `Policy` at
    startup**, not read from disk inside `resolve()`, and `policy_digest` covers all three."
    Every field here is that rule applied to one more fact, and the config keys are
    18-api-sketch.md:1638-1660's `[drivers]` and `[licence]` rows.

    Four fields are not from that list and each is recorded rather than smuggled in:

    * **`enabled`** is carried and **never read by a gate.** 04-driver-system.md:1360 is explicit
      that `[drivers] enabled` is "the gate that is not inside `resolve()` at all", and the
      twenty-six `RejectCode` members contain no member for it, which is the same fact stated
      twice. It is here because `ow drivers list` prints the `NOT ENABLED` column (:2344) and
      `ow doctor` fails on a named-but-unenabled driver, and because `policy_digest` must move
      when it changes. A test asserts two policies differing only in `enabled` yield the same
      candidate set.
    * **`collisions` / `collision_resolution`** carry the `ID_COLLISION_UNQUALIFIED` inputs.
      `Catalog.cards` is a `Mapping[DriverId, DriverCard]` and therefore *cannot express* two
      distributions declaring one id, so the fact cannot reach a gate through the catalog;
      04-driver-system.md:1217-1221 makes the collision a discovery finding and
      `[drivers.resolve] "<id>" = "<dist>"` the explicit disambiguation, which is config and
      belongs here. The seam is reported.
    * **`host_env`** is the environment half of the hardware gate. `ProbeEnv`
      (04-driver-system.md:142-150) is the only host-environment snapshot the plan declares and
      it is a frozen ports type, so it is reused rather than re-declared (INV-21). `None` means
      the caller declared no environment, and then any card declaring a hardware demand at all is
      `HARDWARE_ABSENT` — fail-closed, which is INV-5's direction.
    * **`licence_seeds`** is 04-driver-system.md:1379's third item -- "the tombstone digest
      set" -- in the shape `omniweave_core.drivers.licence` (W3.3) reads it. `compute_tier`
      takes it keyword-only with **no default**, so a `Policy` built with no seeds says so in
      code a reviewer can grep for rather than getting a `forbidden` check that silently never
      fires.

    **There is no `tier_of` override, and there must not be.** DR15 is that an author cannot
    mislabel a tier; an operator-supplied tier map would reinstate exactly that channel one
    level out. The tier is computed from card facts on every call, by `compute_tier`, which is
    pure and is that module's alone.
    """

    allow_tiers: frozenset[LicenceTier] = frozenset({LicenceTier.OPEN})
    jurisdiction: str = ""
    fields_of_use: frozenset[str] = frozenset()
    acks: AckSet = _NO_ACKS
    licence_seeds: LicenceSeeds = _NO_SEEDS
    locked_ids: frozenset[str] = frozenset()
    require_lock: bool = True
    allow_unattested: bool = False
    allow_cost_classes: frozenset[CostClass] = frozenset({CostClass.FREE, CostClass.LOCAL_COMPUTE})
    inproc_ids: frozenset[str] = frozenset()
    isolation_floor: Isolation = Isolation.SUBPROC
    quarantined: frozenset[str] = frozenset()
    enabled: frozenset[str] = frozenset()
    collisions: frozenset[str] = frozenset()
    collision_resolution: Mapping[str, str] = MappingProxyType({})
    driver_config: Mapping[str, Mapping[str, JsonValue]] = MappingProxyType({})
    host_env: ProbeEnv | None = None
    release: str = RELEASE
    policy_digest: str = field(init=False, compare=False, repr=False, default="")

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "policy_digest", _digest_over_fields(self, derived="policy_digest")
        )


@dataclass(frozen=True, slots=True)
class Candidate:
    """One surviving driver. 04-driver-system.md:1384-1389's printed declaration, verbatim.

    `isolation_granted` is **the host's decision, never the card's request** — the field exists so
    that a `[isolation] requires = "inproc"` a policy declined shows up as a granted `subproc`
    plus an `isolation_shortfall` degradation rather than as a claim nobody checked (DR10).
    """

    card: DriverCard
    isolation_granted: Isolation
    effective_config: Mapping[str, JsonValue]
    config_digest: str

    @property
    def driver_id(self) -> str:
        return self.card.identity.id


@dataclass(frozen=True, slots=True)
class Resolution:
    """`resolve()`'s output. **Never contains a chosen driver** (glossary.md:961).

    `candidates` is semantically UNORDERED and emitted in ascending `driver_id` so that
    `resolution_digest` is canonical (02-architecture.md:475, :280; 04-driver-system.md:1371).
    `__post_init__` asserts both the sort and DR5's typing, so a caller cannot construct a
    `Resolution` whose rejections are untyped or whose candidates carry an emergent order.

    **`resolution_digest` has no printed recipe anywhere in the plan** —
    `adr/0007-driver-resolution-keys.md`'s Open section says so in as many words, notes that
    04-driver-system.md's erratum E14 "defines exactly four digest recipes (`card_sha256`,
    `attestation`, `config_digest`, the pins digest) and this is not one of them", and files it as
    a foreign defect. The recipe below is therefore our engineering call and is reported as such:
    the three memo-key strings plus the *outcome* — every candidate's `(driver_id,
    isolation_granted, config_digest)` and every rejection's `(driver_id, code, detail)` — so that
    two runs agreeing on the digest agree on what resolution decided and not merely on what it
    was asked. The `sha256:` prefix is pinned by 04-driver-system.md:2360, which prints
    `resolution_digest sha256:0a37c1be…`.
    """

    requirement: Requirement
    candidates: tuple[Candidate, ...]
    rejected: tuple[Rejection, ...]
    catalog_digest: str
    policy_digest: str
    resolution_digest: str = field(init=False, compare=False, default="")
    degradations: tuple[ResolveDegradation, ...] = ()

    def __post_init__(self) -> None:
        ids = [candidate.driver_id for candidate in self.candidates]
        if ids != sorted(ids):
            raise ValueError(
                f"Resolution.candidates must be in ascending driver_id order: got {ids} "
                f"(04-driver-system.md:1371 — a canonicalisation, not a ranking)"
            )
        for rejection in self.rejected:
            if type(rejection) is not Rejection:
                raise TypeError(
                    f"Resolution.rejected holds {type(rejection).__name__}; DR5 requires a "
                    f"Rejection carrying a typed RejectCode (01-principles.md:210)"
                )
        object.__setattr__(self, "resolution_digest", _SHA256_PREFIX + self._digest())

    def _digest(self) -> str:
        return sha256_canonical(
            {
                "requirement_digest": self.requirement.digest,
                "policy_digest": self.policy_digest,
                "catalog_digest": self.catalog_digest,
                "candidates": [
                    [c.driver_id, c.isolation_granted.value, c.config_digest]
                    for c in self.candidates
                ],
                "rejected": [list(r.row()) for r in self.rejected],
            }
        )

    @property
    def considered(self) -> int:
        """`len(candidates) + len(rejected)`, which DR5 makes a test (04-driver-system.md:1369)."""
        return len(self.candidates) + len(self.rejected)

    def rejection_of(self, driver_id: str) -> Rejection | None:
        for rejection in self.rejected:
            if rejection.driver_id == driver_id:
                return rejection
        return None


# --------------------------------------------------------------------------------------------
# 4. The capability floors. A filter, and never a ranking key
# --------------------------------------------------------------------------------------------


class FloorKind(StrEnum):
    """How one `[capability.<port>]` field is compared. 04-driver-system.md section 2.2's column.

    Four kinds and no fifth, because 2.2's comparison column has four distinct entries and
    `forfeits` "is the only inverted comparison on the whole card, and therefore the only key a
    reviewer should expect to see special-cased in `resolve()`" (:504). A proposed second
    inversion "is a reason to reject the PR" (:512), which is why this is a closed enum rather
    than a callable per field.
    """

    LADDER = "ladder"
    BOOLEAN = "boolean"
    SUPERSET = "superset"
    SUBSET_INVERTED = "subset_inverted"


_PARSE_FLOORS: Final[Mapping[str, FloorKind]] = MappingProxyType(
    {
        **dict.fromkeys(PARSE_LADDERS, FloorKind.LADDER),
        **dict.fromkeys(PARSE_BOOLS, FloorKind.BOOLEAN),
        "math": FloorKind.SUPERSET,
        "forfeits": FloorKind.SUBSET_INVERTED,
        "format_tokens": FloorKind.SUPERSET,
    }
)
_ACQUIRE_FLOORS: Final[Mapping[str, FloorKind]] = MappingProxyType(
    {
        **dict.fromkeys(ACQUIRE_LADDERS, FloorKind.LADDER),
        "schemes": FloorKind.SUPERSET,
        "authn": FloorKind.SUPERSET,
        "ranges": FloorKind.BOOLEAN,
        "streaming": FloorKind.BOOLEAN,
        "trust_class_declared": FloorKind.BOOLEAN,
    }
)
_DERIVE_FLOORS: Final[Mapping[str, FloorKind]] = MappingProxyType(
    {
        **dict.fromkeys(DERIVE_LADDERS, FloorKind.LADDER),
        "items": FloorKind.SUPERSET,
        "scripts": FloorKind.SUPERSET,
        "coreference": FloorKind.BOOLEAN,
        "scope_honoured": FloorKind.BOOLEAN,
    }
)
_EMBED_FLOORS: Final[Mapping[str, FloorKind]] = MappingProxyType(
    {
        **dict.fromkeys(EMBED_LADDERS, FloorKind.LADDER),
        "inputs": FloorKind.SUPERSET,
        "quantization": FloorKind.SUPERSET,
        "instructions": FloorKind.BOOLEAN,
        "multi_vector": FloorKind.BOOLEAN,
    }
)

FLOOR_KINDS: Final[Mapping[Port, Mapping[str, FloorKind]]] = MappingProxyType(
    {
        Port.PARSE: _PARSE_FLOORS,
        Port.ACQUIRE: _ACQUIRE_FLOORS,
        Port.DERIVE: _DERIVE_FLOORS,
        Port.EMBED: _EMBED_FLOORS,
        Port.COMPILE: MappingProxyType({}),
    }
)
"""Every declarable floor, per Port, with its comparison semantics.

The four per-Port tables are DERIVED from `omniweave_core.drivers.card`'s ladder and set
constants rather than re-listing the field names, which is what keeps 04-driver-system.md section
2.2's ten parse ladders in exactly one place: adding a rung there cannot leave a floor comparing
it as a boolean. The keys the card module does not carry as a ladder — `math`, `forfeits`,
`format_tokens`, `schemes`, `authn`, `items`, `scripts`, `inputs`, `quantization` and the six
booleans — are section 2.2's and section 2.4's own annotations, quoted at each site.

`compile` is empty because 04-driver-system.md section 10.3 states the two empty Ports "rather
than implied" and `[capability.compile]` is 09-generation.md's, whose fields are carried on
`DriverCard.compile_capability` as raw JSON. A floor named against `compile/1` is therefore an
unknown floor, which is `CAPABILITY_BELOW_FLOOR` detail `unknown_floor` — never a silent pass."""

_PORT_LADDERS: Final[Mapping[Port, Mapping[str, tuple[str, ...]]]] = MappingProxyType(
    {
        Port.PARSE: PARSE_LADDERS,
        Port.ACQUIRE: ACQUIRE_LADDERS,
        Port.DERIVE: DERIVE_LADDERS,
        Port.EMBED: EMBED_LADDERS,
    }
)

_PORT_SET_MEMBERS: Final[Mapping[Port, Mapping[str, frozenset[str]]]] = MappingProxyType(
    {
        Port.PARSE: PARSE_SETS,
        Port.ACQUIRE: MappingProxyType({"authn": ACQUIRE_AUTHN}),
        Port.DERIVE: MappingProxyType({"items": DERIVE_ITEMS}),
        Port.EMBED: MappingProxyType({"inputs": EMBED_INPUTS, "quantization": EMBED_QUANTIZATIONS}),
    }
)
"""The closed member vocabularies, for the `forfeits` exception only.

An unknown MEMBER of a set-valued floor is normally harmless — "every other set is a floor and an
unknown member only shrinks it" (04-driver-system.md:1501) — so the card loader drops it. `forfeits`
is the one key where ignoring a member "makes the driver look **more** capable", so an unknown
member there is a match failure, `CAPABILITY_BELOW_FLOOR` detail `forfeits_unknown_member`
(:505-511). `schemes` and `scripts` have no closed vocabulary (a URI scheme and a Unicode script
name are open sets), so they are absent here by design."""


def floor_kind(port: Port, name: str) -> FloorKind | None:
    """How `name` is compared for `port`, or `None` when `port` declares no such floor."""
    return FLOOR_KINDS[port].get(name)


def _as_set(value: object) -> frozenset[str] | None:
    if isinstance(value, (frozenset, set, tuple, list)):
        return frozenset(str(member) for member in value)
    return None


def meets_floor(port: Port, name: str, declared: object, floor: object) -> bool:
    """Does `declared` meet `floor` for `port`'s `name` field? **A predicate and nothing else.**

    16-roadmap.md:481 prices this as "one assertion and a class of bugs": *a capability floor is a
    filter and never a ranking key*. The return type is the assertion — there is no score to
    return, no distance, no "how far above the floor", so no caller can accumulate one. The class
    of bugs is what the four `FloorKind` arms exist to prevent:

    * an ordered field compared as a boolean (`spatial = "page_bbox"` is truthy, and so is
      `"none"`), which passes every floor;
    * a set compared with `==`, which refuses a driver supporting `{latex, mathml}` for a
      requirement needing `{latex}`;
    * `forfeits` compared the same way as `math`, which is the inverted one and would admit a
      driver that forfeits exactly what the caller needs.

    Raises `KeyError` on a field `port` does not declare. Callers inside `resolve()` check
    `floor_kind()` first and turn the absence into `CAPABILITY_BELOW_FLOOR` detail
    `unknown_floor`, because `resolve()` never raises.
    """
    kind = FLOOR_KINDS[port][name]
    if kind is FloorKind.LADDER:
        rungs = _PORT_LADDERS[port][name]
        declared_at = rungs.index(str(declared)) if str(declared) in rungs else -1
        floor_at = rungs.index(str(floor)) if str(floor) in rungs else len(rungs)
        return declared_at >= floor_at
    if kind is FloorKind.BOOLEAN:
        return bool(declared) >= bool(floor)
    declared_set, floor_set = _as_set(declared), _as_set(floor)
    if declared_set is None or floor_set is None:
        return False
    if kind is FloorKind.SUPERSET:
        return declared_set >= floor_set
    return declared_set <= floor_set


# --------------------------------------------------------------------------------------------
# 5. The gates, in the fixed order of 04-driver-system.md section 4.8
# --------------------------------------------------------------------------------------------

_PORT_RE: Final = re.compile(r"^(acquire|parse|derive|embed|compile)/([1-9][0-9]*)$")
"""`Requirement.port`'s grammar. `omniweave_core.drivers.card.PORT_RE` is the CARD's spelling of
the same fact and this is the requirement side of it; the two patterns are asserted equal by a
test rather than one importing the other, because a `Requirement` is not a card and a future Port
name added to one and not the other is exactly the drift worth catching."""

_SEMVER_RE: Final = re.compile(r"^(\d+)\.(\d+)\.(\d+)")


@dataclass(frozen=True, slots=True)
class _Subject:
    """One driver under one requirement, with every fact the gates read already resolved.

    Assembled once per (driver, requirement) so no gate reaches back into the catalog or the
    policy for a fact another gate already computed — which is what keeps each gate a predicate
    over its own inputs and the order the only thing that sequences them.
    """

    driver_id: str
    card: DriverCard
    requirement: Requirement
    catalog: Catalog
    policy: Policy
    trust: TrustTier
    probe_status: str

    @property
    def cost_class(self) -> CostClass:
        """The card's declared cost class, `free` when `[cost.model]` is absent.

        04-driver-system.md:740 makes `[cost.model]` author-declared "because it is structural,
        not measured", and a card that declares none has declared no cost — which is `free` and
        never `billed_api`, the direction in which a missing declaration cannot buy anything."""
        return self.card.cost_model.cost_class if self.card.cost_model else CostClass.FREE


_Check = Callable[[_Subject], "Rejection | None"]


class Gate(NamedTuple):
    """One filter of 04-driver-system.md section 4.8's fixed order.

    `codes` is the set of `RejectCode` members this gate can emit, in the order the document
    prints them after the `->`; several gates print two or three, and within such a gate the
    printed order is the only evidence there is, so it is followed and reported.
    """

    name: str
    codes: tuple[RejectCode, ...]
    check: _Check
    plan: str


def _reject(subject: _Subject, code: RejectCode, detail: str) -> Rejection:
    return Rejection(driver_id=subject.driver_id, code=code, detail=detail)


def _gate_port_supported(subject: _Subject) -> Rejection | None:
    major = subject.requirement.port_major
    if major not in PORT_MAJORS_SUPPORTED:
        return _reject(
            subject,
            RejectCode.PORT_UNSUPPORTED,
            f"this build implements Port majors {sorted(PORT_MAJORS_SUPPORTED)}; the requirement "
            f"asks for {subject.requirement.port!r}",
        )
    if subject.card.identity.port_major not in PORT_MAJORS_SUPPORTED:
        return _reject(
            subject,
            RejectCode.PORT_UNSUPPORTED,
            f"the card declares port {subject.card.identity.port}/"
            f"{subject.card.identity.port_major}, a major this build does not implement",
        )
    return None


def _gate_port_matches(subject: _Subject) -> Rejection | None:
    wanted = subject.requirement.port_name
    got = subject.card.identity.port
    if got is not wanted:
        return _reject(
            subject,
            RejectCode.PORT_MISMATCH,
            f"the caller asked for {subject.requirement.port!r} and the card is a "
            f"{got.value}/{subject.card.identity.port_major} driver",
        )
    return None


def _gate_id_unambiguous(subject: _Subject) -> Rejection | None:
    if subject.driver_id not in subject.policy.collisions:
        return None
    if subject.driver_id in subject.policy.collision_resolution:
        return None
    return _reject(
        subject,
        RejectCode.ID_COLLISION_UNQUALIFIED,
        f"two distributions declare {subject.driver_id!r} and no [drivers.resolve] row says "
        f"which wins; a duplicate id never wins silently (DR3)",
    )


def _gate_not_tombstoned(subject: _Subject) -> Rejection | None:
    tombstone: Tombstone | None = subject.catalog.tombstones.get(subject.driver_id)
    if tombstone is None:
        return None
    return _reject(
        subject,
        RejectCode.TOMBSTONED,
        f"{subject.driver_id} is tombstoned: {tombstone.reason}",
    )


def _version_key(raw: str) -> tuple[int, int, int] | None:
    matched = _SEMVER_RE.match(raw)
    if matched is None:
        return None
    return (int(matched[1]), int(matched[2]), int(matched[3]))


def _gate_not_removed(subject: _Subject) -> Rejection | None:
    window = subject.card.deprecation
    if window is None:
        return None
    release, removed = _version_key(subject.policy.release), _version_key(window.removed_in)
    if release is None or removed is None:
        return None
    if release >= removed:
        replacement = window.replaced_by or "no successor"
        return _reject(
            subject,
            RejectCode.DEPRECATED_REMOVED,
            f"removed_in = {window.removed_in} and this build is {subject.policy.release}; "
            f"use {replacement} ({window.reason})",
        )
    return None


def _gate_card_schema(subject: _Subject) -> Rejection | None:
    if subject.card.card_schema in CARDS_SUPPORTED:
        return None
    return _reject(
        subject,
        RejectCode.CARD_SCHEMA_TOO_NEW,
        f"card_schema = {subject.card.card_schema} and this build supports "
        f"{sorted(CARDS_SUPPORTED)}; the fix is an upgrade and never an edit to the card",
    )


def _gate_format(subject: _Subject) -> Rejection | None:
    wanted = subject.requirement.format
    if not wanted:
        return None
    formats = subject.card.capability.formats
    if wanted in formats:
        return None
    return _reject(
        subject,
        RejectCode.FORMAT_UNSUPPORTED,
        f"{wanted!r} is not in [capability] formats = {list(formats)}",
    )


def _gate_produces(subject: _Subject) -> Rejection | None:
    demanded = frozenset(subject.requirement.requires_produces)
    produces = subject.card.capability.produces
    missing = sorted(kind.value for kind in demanded - produces)
    if not missing:
        return None
    return _reject(
        subject,
        RejectCode.PRODUCES_INSUFFICIENT,
        f"[capability] produces = {sorted(kind.value for kind in produces)} does not cover "
        f"{missing}",
    )


def _gate_granularity(subject: _Subject) -> Rejection | None:
    wanted = subject.requirement.granularity
    if wanted is None:
        return None
    declared = subject.card.identity.granularity
    if declared == wanted:
        return None
    return _reject(
        subject,
        RejectCode.GRANULARITY_MISMATCH,
        f"[driver] granularity = {declared!r} and the requirement asks for {wanted!r}",
    )


def _port_capability(subject: _Subject) -> object | None:
    """The `[capability.<port>]` record for this card's Port, or `None` when it declares none."""
    return {
        Port.PARSE: subject.card.parse,
        Port.ACQUIRE: subject.card.acquire,
        Port.DERIVE: subject.card.derive,
        Port.EMBED: subject.card.embed,
    }.get(subject.card.identity.port)


def _declared_floor_value(capability: object, name: str) -> object:
    if name == "format_tokens":
        pairs = getattr(capability, "format_tokens", ())
        return frozenset(pair.token for pair in pairs)
    return getattr(capability, name)


def _gate_capability(subject: _Subject) -> Rejection | None:
    """Gate 7 — every requested floor met, plus `input_kind` and the two permanent card defects.

    Three things ride on this one gate because 04-driver-system.md gives them no other code:

    * **`input_kind`.** 13-quality.md:218 requires two requirements differing only in
      `input_kind` to resolve differently, and section 4.8's printed order has no gate for it and
      the twenty-six members no code. `[capability] consumes` is a `[capability]` set, so the fit
      failure is `CAPABILITY_BELOW_FLOOR` detail `input_kind_not_consumed`. Reported as a finding.
    * **`forfeits_unknown_member`** (04-driver-system.md:505-511), which is a match failure by
      name because the card loader deliberately KEEPS an unknown `forfeits` member where it drops
      every other set's.
    * **`scope_not_honoured`** (04-driver-system.md:686-689): `scope_honoured = false` on a
      `derive` card "is the one capability value that makes a driver permanently
      **unactivatable** rather than merely unselected", refused "for every requirement with
      `CAPABILITY_BELOW_FLOOR` detail `scope_not_honoured`".
    """
    port = subject.card.identity.port
    capability = _port_capability(subject)
    wanted_kind = subject.requirement.input_kind
    if wanted_kind is not None and wanted_kind not in subject.card.capability.consumes:
        return _reject(
            subject,
            RejectCode.CAPABILITY_BELOW_FLOOR,
            f"input_kind_not_consumed: [capability] consumes = "
            f"{sorted(k.value for k in subject.card.capability.consumes)} does not include "
            f"{wanted_kind.value!r}",
        )
    if capability is None:
        if subject.requirement.floors:
            return _reject(
                subject,
                RejectCode.CAPABILITY_BELOW_FLOOR,
                f"the card declares no [capability.{port.value}] table, so the floors "
                f"{sorted(subject.requirement.floors)} are unmet by absence",
            )
        return None
    if port is Port.DERIVE and not getattr(capability, "scope_honoured", False):
        return _reject(
            subject,
            RejectCode.CAPABILITY_BELOW_FLOOR,
            "scope_not_honoured: [capability.derive] scope_honoured = false, which makes the "
            "driver permanently unactivatable rather than merely unselected",
        )
    if port is Port.PARSE:
        unknown = sorted(getattr(capability, "forfeits", frozenset()) - PARSE_SETS["forfeits"])
        if unknown:
            return _reject(
                subject,
                RejectCode.CAPABILITY_BELOW_FLOOR,
                f"forfeits_unknown_member: {unknown} is outside the closed forfeits vocabulary, "
                f"and an ignored member would make the driver look MORE capable",
            )
    return _first_unmet_floor(subject, port, capability)


def _first_unmet_floor(subject: _Subject, port: Port, capability: object) -> Rejection | None:
    for name in sorted(subject.requirement.floors):
        floor = subject.requirement.floors[name]
        kind = floor_kind(port, name)
        if kind is None:
            return _reject(
                subject,
                RejectCode.CAPABILITY_BELOW_FLOOR,
                f"unknown_floor: {name!r} is not a [capability.{port.value}] field, so no card "
                f"can meet it; the declarable floors are {sorted(FLOOR_KINDS[port])}",
            )
        declared = _declared_floor_value(capability, name)
        if not meets_floor(port, name, declared, floor):
            return _reject(
                subject,
                RejectCode.CAPABILITY_BELOW_FLOOR,
                f"{name} declares {_shown(declared)} and the floor is {_shown(floor)} "
                f"(compared {kind.value})",
            )
    return None


def _shown(value: object) -> str:
    if isinstance(value, (frozenset, set)):
        return "{" + ", ".join(sorted(str(member) for member in value)) + "}"
    return repr(value)


def _gate_licence(subject: _Subject) -> Rejection | None:
    """Gate 8 — tier allowed, then acknowledged. Three codes in the printed order.

    04-driver-system.md:1348-1350 prints `LICENCE_TIER_NOT_ALLOWED | LICENCE_ACK_MISSING |
    LICENCE_ACK_STALE` and :1917 confirms the sequence in prose: a restricted driver on a fresh
    install "is refused twice over ... once by the tier allowlist and once by the missing ack".

    The territory and field-of-use selectors are here too. :1918-1921 makes them "a *local*
    refusal rather than a global one" and assigns them no code of their own, so they carry
    `LICENCE_TIER_NOT_ALLOWED` with a detail naming the excluded jurisdiction or field. Reported
    as a finding.
    """
    tier = _tier_of(subject)
    if tier not in subject.policy.allow_tiers:
        return _reject(
            subject,
            RejectCode.LICENCE_TIER_NOT_ALLOWED,
            f"computed tier {tier.value!r} is not in [licence] allow_tiers = "
            f"{sorted(t.value for t in subject.policy.allow_tiers)}",
        )
    local = _local_licence_refusal(subject)
    if local is not None:
        return local
    return _first_ack_failure(subject)


def _tier_of(subject: _Subject) -> LicenceTier:
    """The computed tier of this card's licence facts. Never declared, never overridden (DR15).

    `omniweave_core.drivers.licence.compute_tier` (W3.3) is the one implementation and it is pure,
    so calling it inside `resolve()` costs purity nothing. `seeds` is `Policy.licence_seeds`,
    which is 04-driver-system.md:1379's tombstone digest set loaded at startup.
    """
    return compute_tier(
        subject.card.licence_code,
        subject.card.licence_weights,
        seeds=subject.policy.licence_seeds,
    )


def _local_licence_refusal(subject: _Subject) -> Rejection | None:
    """`[licence] jurisdiction` and `[licence] fields_of_use`, "a *local* refusal" (:1918-1921).

    These two are the caller's half of the split `omniweave_core.drivers.licence`'s own docstring
    states: facts -> tier and text -> ack validity are that module's; tier -> allowed and
    exclusion -> local refusal are this one's. Neither exclusion has a `RejectCode` of its own
    among the twenty-six, so both carry `LICENCE_TIER_NOT_ALLOWED` with a detail naming the
    excluded jurisdiction or field. Reported as a finding.
    """
    tables = (("code", subject.card.licence_code), ("weights", subject.card.licence_weights))
    jurisdiction = subject.policy.jurisdiction
    for which, fact in tables:
        if fact is None:
            continue
        if jurisdiction and jurisdiction in fact.territory_excluded:
            return _reject(
                subject,
                RejectCode.LICENCE_TIER_NOT_ALLOWED,
                f"[licence.{which}] territory_excluded names {jurisdiction!r}, which is "
                f"[licence] jurisdiction",
            )
        barred = sorted(subject.policy.fields_of_use & frozenset(fact.field_of_use_excluded))
        if barred:
            return _reject(
                subject,
                RejectCode.LICENCE_TIER_NOT_ALLOWED,
                f"[licence.{which}] field_of_use_excluded bars {barred}, which [licence] "
                f"fields_of_use declares",
            )
    return None


def _first_ack_failure(subject: _Subject) -> Rejection | None:
    """One `check_ack()` per licensed artefact, `code` before `weights`.

    Per artefact and not per card, because "one row per licensed artefact" (:1903) and the Datalab
    trap is exactly a permissive code licence over restrictive weights (01-principles.md:205-209):
    an operator who acknowledged the code licence has not thereby acknowledged the weights one.
    `installed` is the card's own recorded `licence_sha256` -- the digest of the text as installed
    -- because `resolve()` may not read the file (:1911).

    `AckVerdict.message` carries the hash diff and the index at which the two digests first
    differ, which is what makes 04-driver-system.md:1911's required test a test of something an
    operator can act on rather than of a boolean. A non-`restricted` artefact returns
    `NOT_REQUIRED`, which `AckVerdict.valid` treats as passing: an ack is required for
    `restricted` and for nothing else (:1890).
    """
    artefacts = (
        (AckWhich.CODE, subject.card.licence_code),
        (AckWhich.WEIGHTS, subject.card.licence_weights),
    )
    for which, fact in artefacts:
        if fact is None or not fact.licence_sha256:
            continue
        verdict = check_ack(
            driver=subject.driver_id,
            which=which,
            tier=tier_of(fact, seeds=subject.policy.licence_seeds),
            installed=fact.licence_sha256,
            acks=subject.policy.acks,
        )
        if verdict.valid:
            continue
        code = (
            RejectCode.LICENCE_ACK_STALE
            if verdict.status is AckStatus.STALE
            else RejectCode.LICENCE_ACK_MISSING
        )
        return _reject(subject, code, verdict.message)
    return None


def _gate_cost_class(subject: _Subject) -> Rejection | None:
    declared = subject.cost_class
    ceiling = subject.requirement.max_cost_class
    if COST_CLASS_ORDER.index(declared) > COST_CLASS_ORDER.index(ceiling):
        return _reject(
            subject,
            RejectCode.COST_CLASS_NOT_PERMITTED,
            f"[cost.model] class = {declared.value!r} is above the requirement's "
            f"max_cost_class = {ceiling.value!r}",
        )
    if declared not in subject.policy.allow_cost_classes:
        return _reject(
            subject,
            RejectCode.COST_CLASS_NOT_PERMITTED,
            f"[cost.model] class = {declared.value!r} is not in [drivers.cost] allow_classes = "
            f"{sorted(c.value for c in subject.policy.allow_cost_classes)}",
        )
    return None


def _gate_hardware(subject: _Subject) -> Rejection | None:
    """Gate 10 — hardware satisfiable. `HARDWARE_ABSENT | BINARY_ABSENT`, in the printed order.

    The environment half is `Policy.host_env`, a `ProbeEnv`. Two facts the plan's own snapshot
    cannot answer are named rather than faked:

    * **`[hardware] ram_gb_min` has no `ProbeEnv` field.** 04-driver-system.md:144-150 declares
      seven fields and none is RAM, so a RAM floor is not decidable from `resolve()`'s three
      arguments. It is left to preflight, which runs in the worker that would run the driver, and
      it is reported as a finding.
    * **`host_env is None`** means the caller declared no environment. Any card declaring a
      hardware demand at all is then `HARDWARE_ABSENT` detail `host_env_undeclared`, because
      INV-5's direction is that nothing runs until somebody said so.
    """
    hardware = subject.card.hardware
    demands = (
        hardware.gpu != "none",
        hardware.vram_gb_min > 0.0,
        hardware.ram_gb_min > 0.0,
        bool(hardware.cpu_arch),
        bool(hardware.os),
        hardware.needs_network,
        bool(hardware.needs_binaries),
    )
    env = subject.policy.host_env
    if env is None:
        if any(demands):
            return _reject(
                subject,
                RejectCode.HARDWARE_ABSENT,
                "host_env_undeclared: the card declares a [hardware] demand and Policy.host_env "
                "is None, so nothing can certify it",
            )
        return None
    return _first_hardware_shortfall(subject, env)


def _first_hardware_shortfall(subject: _Subject, env: ProbeEnv) -> Rejection | None:
    """The five `HARDWARE_ABSENT` facts then `BINARY_ABSENT`, in section 4.8's printed order.

    Written as a TABLE rather than as a chain of `if`s so that the order the document prints —
    `HARDWARE_ABSENT | BINARY_ABSENT`, hardware before binaries — is a readable sequence rather
    than a property of where a reviewer stopped adding branches. `ram_gb_min` is deliberately
    absent; see `_gate_hardware`.
    """
    hardware = subject.card.hardware
    shortfalls: tuple[tuple[bool, RejectCode, str], ...] = (
        (
            hardware.gpu == "required" and not env.gpu_present,
            RejectCode.HARDWARE_ABSENT,
            '[hardware] gpu = "required" and ProbeEnv.gpu_present is False',
        ),
        (
            hardware.vram_gb_min > 0.0 and env.vram_gb < hardware.vram_gb_min,
            RejectCode.HARDWARE_ABSENT,
            f"[hardware] vram_gb_min = {hardware.vram_gb_min} and this host reports {env.vram_gb}",
        ),
        (
            bool(hardware.cpu_arch) and env.machine not in hardware.cpu_arch,
            RejectCode.HARDWARE_ABSENT,
            f"[hardware] cpu_arch = {list(hardware.cpu_arch)} and this host is {env.machine!r}",
        ),
        (
            bool(hardware.os) and env.platform not in hardware.os,
            RejectCode.HARDWARE_ABSENT,
            f"[hardware] os = {list(hardware.os)} and this host is {env.platform!r}",
        ),
        (
            hardware.needs_network and env.offline,
            RejectCode.HARDWARE_ABSENT,
            "[hardware] needs_network = true and this run is --offline",
        ),
        (
            bool(_absent_binaries(hardware.needs_binaries, env)),
            RejectCode.BINARY_ABSENT,
            f"[hardware] needs_binaries names {_absent_binaries(hardware.needs_binaries, env)}, "
            f"which shutil.which() did not find",
        ),
    )
    for failed, code, detail in shortfalls:
        if failed:
            return _reject(subject, code, detail)
    return None


def _absent_binaries(needed: Sequence[str], env: ProbeEnv) -> list[str]:
    """Every `[hardware] needs_binaries` name `ProbeEnv.which` could not resolve."""
    return sorted(name for name in needed if not env.which.get(name))


def _gate_witness_set(subject: _Subject) -> Rejection | None:
    """Gate 11 — witness set or cohort, if billed and corpus-granularity.

    04-driver-system.md:730-738 is the whole rule. A corpus-granularity driver reads across units,
    so "its dependency footprint cannot be inferred from what the runner fed it": it must declare
    `witness_set` in `[capability] produces` or accept a Cohort digest, and "a `billed_api`
    corpus-granularity driver declaring **neither** is refused with `NO_WITNESS_SET`, because the
    alternative is a paid derivation whose incremental correctness nothing can check". The cohort
    route is explicitly the *free* driver's ("a free corpus driver may take the cohort route
    because re-deriving it is cheap"), so for a billed corpus driver the gate reduces to the one
    card fact `[capability] produces` carries.
    """
    if subject.cost_class is not CostClass.BILLED_API:
        return None
    if subject.card.identity.granularity != "corpus":
        return None
    if ArtifactKind.WITNESS_SET in subject.card.capability.produces:
        return None
    return _reject(
        subject,
        RejectCode.NO_WITNESS_SET,
        "a billed_api corpus-granularity driver must declare witness_set in [capability] "
        "produces; the cohort route is the free driver's (04-driver-system.md:736)",
    )


def _gate_probe(subject: _Subject) -> Rejection | None:
    """Gate 12 — `probe status != unavailable`, and `unknown` PASSES.

    04-driver-system.md:1289: "`resolve()` reads `probe_status` and treats `unknown` as **passing**
    the filter — an unprobed driver is a candidate, not a refusal." Preflight then probes exactly
    the `unknown` candidates, out of process, and re-resolves once against the refreshed catalog;
    `catalog_digest` includes `probe_status`, so the second pass cannot read the first's answer.
    """
    if subject.probe_status != "unavailable":
        return None
    return _reject(
        subject,
        RejectCode.PROBE_UNAVAILABLE,
        f"the catalog carries probe_status = 'unavailable' for {subject.driver_id}; "
        f"ProbeVerdict.missing is machine-actionable and fix_hint is printed",
    )


def _gate_not_quarantined(subject: _Subject) -> Rejection | None:
    if subject.driver_id not in subject.policy.quarantined:
        return None
    return _reject(
        subject,
        RejectCode.QUARANTINED,
        f"{subject.driver_id} is quarantined for this run (three crashes in 60 s, "
        f"[drivers] crash_quarantine); the plan re-routes",
    )


def _pin_names(subject: _Subject) -> bool:
    """Does the requirement pin this driver? `<id>` or the `<id>@<dist>` form of :1476."""
    pinned = subject.requirement.pinned
    if not pinned:
        return False
    return pinned.split("@", 1)[0] == subject.driver_id


def _gate_attested(subject: _Subject) -> Rejection | None:
    if subject.card.attested or subject.policy.allow_unattested or _pin_names(subject):
        return None
    return _reject(
        subject,
        RejectCode.UNATTESTED,
        "the recomputed attestation does not match the card's, and neither "
        "[drivers] allow_unattested nor an explicit pin waives it "
        "(attestation is tamper-evidence, not authentication)",
    )


def _gate_lockfile(subject: _Subject) -> Rejection | None:
    if not subject.policy.require_lock or subject.driver_id in subject.policy.locked_ids:
        return None
    return _reject(
        subject,
        RejectCode.NOT_IN_LOCKFILE,
        f"[drivers] require_lock = true and {subject.driver_id} has no [[driver]] row in "
        f"omniweave.lock",
    )


def _gate_isolation(subject: _Subject) -> Rejection | None:
    """Gate 16 — isolation grantable. `ISOLATION_NOT_PERMITTED | TRUST_INSUFFICIENT`.

    **`TRUST_INSUFFICIENT` has no producer that section 6.1 does not convert into a
    `Degradation`, and this is the reading under which it has one.** Section 4.8:1358 lists
    `isolation grantable` as a refusal with two codes. Three hundred lines later, :1645-1648 says
    `[isolation] requires` on the card "is a *request* and the host may only **tighten** it: a
    card asking for `inproc` that fails any conjunct runs `subproc`
    (`Degradation(kind="isolation_shortfall")`, not a refusal)". That leaves exactly two refusals
    available:

    * a card requesting `wasm`, which "is in the vocabulary and not built at v1" (:1650) —
      `ISOLATION_NOT_PERMITTED`;
    * an operator naming an id in `[drivers] inproc` — "a reviewable operator act, never a card
      claim" (18-api-sketch.md:1642) — whose computed trust bars `inproc`, since "no config key
      widens the first four" (:1645). Downgrading that silently would make the config line a
      no-op that looks like it worked, so it is `TRUST_INSUFFICIENT`.

    The card-request case stays a degradation, which `_grant_isolation()` records. DR9's six
    conjuncts are filed at `omniweave_core/drivers/policy.py` by 04-driver-system.md:2678; that
    module does not exist and no agent in this wave owns it, so they live here and moving them is
    a mechanical extraction.
    """
    requested = subject.card.isolation.requires
    if requested not in ISOLATION_CONTAINMENT:
        return _reject(
            subject,
            RejectCode.ISOLATION_NOT_PERMITTED,
            f"[isolation] requires = {requested.value!r}, which is in the vocabulary and not "
            f"built at v1",
        )
    if subject.driver_id in subject.policy.inproc_ids and subject.trust not in INPROC_TRUST:
        return _reject(
            subject,
            RejectCode.TRUST_INSUFFICIENT,
            f"[drivers] inproc names {subject.driver_id}, whose computed trust is "
            f"{subject.trust.value!r} and not one of "
            f"{sorted(t.value for t in INPROC_TRUST)}; no config key widens DR9's first four",
        )
    return None


GATE_ORDER: Final[tuple[Gate, ...]] = (
    Gate(
        "port_major_supported",
        (RejectCode.PORT_UNSUPPORTED,),
        _gate_port_supported,
        "04-driver-system.md:1341",
    ),
    Gate(
        "port_matches_requirement",
        (RejectCode.PORT_MISMATCH,),
        _gate_port_matches,
        "04-driver-system.md:1563 (group); :1569-1573 (meaning). ORDER IS OURS",
    ),
    Gate(
        "id_unambiguous",
        (RejectCode.ID_COLLISION_UNQUALIFIED,),
        _gate_id_unambiguous,
        "04-driver-system.md:1217-1221; :1563 (group). ORDER IS OURS",
    ),
    Gate(
        "not_tombstoned", (RejectCode.TOMBSTONED,), _gate_not_tombstoned, "04-driver-system.md:1342"
    ),
    Gate(
        "not_removed",
        (RejectCode.DEPRECATED_REMOVED,),
        _gate_not_removed,
        "04-driver-system.md:1585-1588; :1563 (group). ORDER IS OURS",
    ),
    Gate(
        "card_schema_supported",
        (RejectCode.CARD_SCHEMA_TOO_NEW,),
        _gate_card_schema,
        "04-driver-system.md:1343",
    ),
    Gate(
        "format_supported",
        (RejectCode.FORMAT_UNSUPPORTED,),
        _gate_format,
        "04-driver-system.md:1344",
    ),
    Gate(
        "produces_sufficient",
        (RejectCode.PRODUCES_INSUFFICIENT,),
        _gate_produces,
        "04-driver-system.md:1345",
    ),
    Gate(
        "granularity_matches",
        (RejectCode.GRANULARITY_MISMATCH,),
        _gate_granularity,
        "04-driver-system.md:1346",
    ),
    Gate(
        "capability_floors_met",
        (RejectCode.CAPABILITY_BELOW_FLOOR,),
        _gate_capability,
        "04-driver-system.md:1347; :505-511; :686-689; 13-quality.md:218",
    ),
    Gate(
        "licence_allowed_and_acknowledged",
        (
            RejectCode.LICENCE_TIER_NOT_ALLOWED,
            RejectCode.LICENCE_ACK_MISSING,
            RejectCode.LICENCE_ACK_STALE,
        ),
        _gate_licence,
        "04-driver-system.md:1348-1350",
    ),
    Gate(
        "cost_class_permitted",
        (RejectCode.COST_CLASS_NOT_PERMITTED,),
        _gate_cost_class,
        "04-driver-system.md:1351",
    ),
    Gate(
        "hardware_satisfiable",
        (RejectCode.HARDWARE_ABSENT, RejectCode.BINARY_ABSENT),
        _gate_hardware,
        "04-driver-system.md:1352",
    ),
    Gate(
        "witness_set_or_cohort",
        (RejectCode.NO_WITNESS_SET,),
        _gate_witness_set,
        "04-driver-system.md:1353",
    ),
    Gate(
        "probe_not_unavailable",
        (RejectCode.PROBE_UNAVAILABLE,),
        _gate_probe,
        "04-driver-system.md:1354",
    ),
    Gate(
        "not_quarantined",
        (RejectCode.QUARANTINED,),
        _gate_not_quarantined,
        "04-driver-system.md:1355",
    ),
    Gate(
        "attested_or_pinned", (RejectCode.UNATTESTED,), _gate_attested, "04-driver-system.md:1356"
    ),
    Gate("in_lockfile", (RejectCode.NOT_IN_LOCKFILE,), _gate_lockfile, "04-driver-system.md:1357"),
    Gate(
        "isolation_grantable",
        (RejectCode.ISOLATION_NOT_PERMITTED, RejectCode.TRUST_INSUFFICIENT),
        _gate_isolation,
        "04-driver-system.md:1358; :1645-1650",
    ),
)
"""**The gate order, as data.** 04-driver-system.md:1340-1360 is the definition site.

Nineteen gates: the sixteen the document prints, plus one each for `PORT_MISMATCH`,
`ID_COLLISION_UNQUALIFIED` and `DEPRECATED_REMOVED` — three members section 5.3:1563 files under
"resolve — identity" and section 4.8's printed order does not place. Their *position* is our
engineering call and each `Gate.plan` says so in as many words; their existence is not.

The order is observable and therefore load-bearing: which `RejectCode` a caller sees for a driver
failing several gates is decided here, and that code is what `ow drivers explain` prints. Two
tallies elsewhere in the plan are wrong against this enumeration and are reported: 16-roadmap.md:481
prices W3.1 at "eight gates in a fixed order", and section 4.8's own list omits three of the
twenty-one resolve codes section 5.3 assigns."""


# --------------------------------------------------------------------------------------------
# 6. resolve(), and the memo
# --------------------------------------------------------------------------------------------


class MemoStats(NamedTuple):
    """The memo's hit counter, which 04-driver-system.md:1442 makes a recorded fact.

    "One `resolution_report` row per `(run_id, resolution_digest)` **with a hit counter** records
    what happened; per-unit `route_decision` rows for resolution were rejected — 4,000 JSON rows
    for one PDF." `hits` is what that counter counts: a 42-part document costs one resolve and
    forty-one hits.
    """

    entries: int
    hits: int
    misses: int
    evictions: int


_MEMO: dict[tuple[str, str, str], Resolution] = {}
_MEMO_HITS = [0, 0, 0]  # hits, misses, evictions


def memo_stats() -> MemoStats:
    """The memo's occupancy and its hit counter."""
    return MemoStats(len(_MEMO), _MEMO_HITS[0], _MEMO_HITS[1], _MEMO_HITS[2])


def clear_memo() -> None:
    """Drop every memoised `Resolution` and reset the counters.

    The plan's memo dies with its `Catalog` (04-driver-system.md:1436) and this one cannot; see
    the module docstring. A run that ends, or a test that wants a cold memo, calls this.
    """
    _MEMO.clear()
    _MEMO_HITS[:] = [0, 0, 0]


def resolve(requirement: Requirement, catalog: Catalog, policy: Policy) -> Resolution:
    """`resolve(Requirement, Catalog, RoutePolicy) -> Resolution` — 02-architecture.md:237.

    **Pure**, in the strong sense that everything it reads is inside its three arguments: no
    import, no clock, no filesystem, no network, no environment (04-driver-system.md:1376). It
    never raises — a zero-candidate `Resolution` *is* the error message (:1366) — and it never
    ranks: `candidates` comes back sorted on `driver_id`, "a canonicalisation forced by
    `resolution_digest` and not a ranking" (02-architecture.md:280).

    **Memoised on `(requirement_digest, policy_digest, catalog_digest)`** — three strings
    (04-driver-system.md:1392-1394), which supersede the charter's six-tuple because that tuple
    omitted four `Requirement` fields that all change the answer. Bounded at `RESOLVE_MEMO_MAX`,
    least-recently-used first. `resolve_uncached()` is the same computation with the memo out of
    the way, which is what a determinism property has to call: two equal returns from this
    function prove memoisation and not purity.
    """
    key = (requirement.digest, policy.policy_digest, catalog.catalog_digest)
    cached = _MEMO.pop(key, None)
    if cached is not None:
        _MEMO[key] = cached  # LRU: re-insert at the newest end
        _MEMO_HITS[0] += 1
        return cached
    _MEMO_HITS[1] += 1
    computed = resolve_uncached(requirement, catalog, policy)
    _MEMO[key] = computed
    while len(_MEMO) > RESOLVE_MEMO_MAX:
        _MEMO.pop(next(iter(_MEMO)))
        _MEMO_HITS[2] += 1
    return computed


def resolve_uncached(requirement: Requirement, catalog: Catalog, policy: Policy) -> Resolution:
    """`resolve()` with the memo bypassed. Same value, every time, for the same three arguments."""
    candidates: list[Candidate] = []
    rejected: list[Rejection] = []
    degradations: list[ResolveDegradation] = []
    for driver_id in sorted(catalog.cards):
        subject = _Subject(
            driver_id=driver_id,
            card=catalog.cards[driver_id],
            requirement=requirement,
            catalog=catalog,
            policy=policy,
            trust=catalog.trust[driver_id],
            probe_status=catalog.probe_status[driver_id],
        )
        rejection = _first_rejection(subject)
        if rejection is not None:
            rejected.append(rejection)
            continue
        candidate = _candidate_of(subject, degradations)
        if isinstance(candidate, Rejection):
            rejected.append(candidate)
            continue
        candidates.append(candidate)
        degradations.extend(_deprecation_degradation(subject))
    return Resolution(
        requirement=requirement,
        candidates=tuple(candidates),
        rejected=tuple(rejected),
        catalog_digest=catalog.catalog_digest,
        policy_digest=policy.policy_digest,
        degradations=tuple(degradations),
    )


def _first_rejection(subject: _Subject) -> Rejection | None:
    """Walk `GATE_ORDER` and return the FIRST refusal. The order is the specification."""
    for gate in GATE_ORDER:
        rejection = gate.check(subject)
        if rejection is not None:
            return Rejection(
                driver_id=rejection.driver_id,
                code=rejection.code,
                detail=rejection.detail,
                gate=gate.name,
            )
    return None


def _grant_isolation(subject: _Subject, degradations: list[ResolveDegradation]) -> Isolation:
    """The HOST's isolation decision — DR9's conjuncts, and a shortfall is not a refusal.

    04-driver-system.md:1636-1643 prints the six conjuncts `inproc` requires **all** of:
    `trust in {first_party, vendored}` AND `cost.model.class == "free"` AND
    `hardware.gpu == "none"` AND `hardware.needs_network == false` AND the `fuzz` conformance
    suite is green AND the id is listed in `omniweave.toml [drivers] inproc`. `[isolation]
    requires` on the card "is a *request* and the host may only **tighten** it": a card asking
    for `inproc` that fails any conjunct runs `subproc` with
    `Degradation(kind="isolation_shortfall")` and **not** a refusal (:1646), and a card asking
    for `subproc` "can never be relaxed to `inproc` by config".

    **`[drivers] isolation_floor` is read as the mode for every driver NOT named in
    `[drivers] inproc`, and that is our engineering call.** Taken literally as a global floor it
    contradicts the shipped configuration: 18-api-sketch.md:1640 ships
    `isolation_floor = "subproc"` while :1642 and 04-driver-system.md:1652 ship
    `inproc = ["parse.office.anydoc"]`, and if `subproc` tightened the per-id list too then
    "exactly one driver is `inproc`-eligible and it is named in the shipped config" could never
    be true of any run. The `[drivers] inproc` list is the sixth conjunct and "a reviewable
    operator act, never a card claim", so it is the grant and the floor is the default. Reported.

    The plan states this enumeration three ways — "DR9's four structural conditions"
    (01-principles.md:216), "DR9's five conditions ... plus an id in `[drivers] inproc`"
    (02-architecture.md:425, 14-security.md:470) and "DR9's six conjuncts"
    (04-driver-system.md:2129, :2678). They reconcile — four unwidenable card facts, plus
    fuzz-green, plus the config id — but the three tallies are reported.

    DR9's conjuncts are filed at `omniweave_core/drivers/policy.py` by 04-driver-system.md:2678,
    "the six conjuncts, in one function, with one test per conjunct". That module does not exist
    and no agent in this wave owns it; `_unmet_inproc_conjuncts()` is that one function, and
    moving it there later is a mechanical extraction.
    """
    if subject.card.isolation.requires is not Isolation.INPROC:
        return subject.card.isolation.requires
    unmet = _unmet_inproc_conjuncts(subject)
    if not unmet:
        return Isolation.INPROC
    degradations.append(
        ResolveDegradation(
            kind="isolation_shortfall",
            driver_id=subject.driver_id,
            detail=f"[isolation] requires = 'inproc' and DR9 is unmet on {unmet}; granted "
            f"{subject.policy.isolation_floor.value}",
        )
    )
    return subject.policy.isolation_floor


def _unmet_inproc_conjuncts(subject: _Subject) -> list[str]:
    hardware = subject.card.hardware
    checks = (
        ("trust", subject.trust in INPROC_TRUST),
        ("cost_class_free", subject.cost_class is CostClass.FREE),
        ("gpu_none", hardware.gpu == "none"),
        ("needs_network_false", not hardware.needs_network),
        ("fuzz_suite_green", subject.card.quality.suites.get("fuzz") == "pass"),
        ("listed_in_drivers_inproc", subject.driver_id in subject.policy.inproc_ids),
    )
    return [name for name, held in checks if not held]


def _candidate_of(
    subject: _Subject, degradations: list[ResolveDegradation]
) -> Candidate | Rejection:
    """Build the `Candidate`, or reject when the supplied config fails the card's `[config]`.

    **Section 4.8's printed order has no gate for a bad `[drivers."<id>"] config` value**, and
    `ConfigSchema.effective()` raises `ConfigError` — which `resolve()` may not propagate, because
    a zero-candidate `Resolution` is the error message and never a raise (:1366). So the failure
    is a rejection emitted at `Candidate` construction, after every gate has passed, carrying
    `CARD_INVALID` — the one member of the twenty-six that covers "the `[config]` schema and the
    supplied values do not agree". Reported as a finding.
    """
    supplied = subject.policy.driver_config.get(subject.driver_id, {})
    try:
        effective = subject.card.config.effective(supplied)
    except ConfigError as exc:
        return _reject(
            subject,
            RejectCode.CARD_INVALID,
            f"config_invalid: {exc}",
        )
    return Candidate(
        card=subject.card,
        isolation_granted=_grant_isolation(subject, degradations),
        effective_config=MappingProxyType(dict(effective)),
        config_digest=sha256_canonical(effective),
    )


def _deprecation_degradation(subject: _Subject) -> Iterable[ResolveDegradation]:
    """`since <= RELEASE < removed_in` records a degradation and still runs the driver (:1585)."""
    window = subject.card.deprecation
    if window is None:
        return ()
    release = _version_key(subject.policy.release)
    since, removed = _version_key(window.since), _version_key(window.removed_in)
    if release is None or since is None or removed is None:
        return ()
    if not since <= release < removed:
        return ()
    return (
        ResolveDegradation(
            kind="deprecation",
            driver_id=subject.driver_id,
            detail=f"deprecated since {window.since}, removed in {window.removed_in}; "
            f"use {window.replaced_by or 'no successor'} ({window.reason})",
        ),
    )


# --------------------------------------------------------------------------------------------
# 7. resolution_report()
# --------------------------------------------------------------------------------------------


def resolution_report(resolution: Resolution) -> Mapping[str, JsonValue]:
    """The `resolution_report` row's payload. **One row per `(run_id, resolution_digest)`.**

    04-driver-system.md:1442 and glossary.md:962: one row per resolution with a hit counter, "not
    one per unit, because a 4,000-page PDF must not write 4,000 report rows". Two columns are
    named by the plan and both are here:

    * **`requirement_json`** "already holds the whole requirement in canonical JSON, one row per
      resolution" (:1432) — which is also what makes the three-digest memo key debuggable, since
      `('a3f1…', 'b7c2…', 'd9e0…')` says nothing on its own (ADR-7).
    * **`report_json`** "stores the enum's own wire value (the lower-case member name)" per
      rejection (:1446, 02-architecture.md:924), and `ow drivers explain` resolves that through
      `codes.toml` to the numeric and the fix command, exactly as it does for a `Diag`.

    `run_id` is not here: it is the runtime's half of the primary key, and this module has no
    `RunContext` (INV-6).
    """
    return MappingProxyType(
        {
            "resolution_digest": resolution.resolution_digest,
            "requirement_digest": resolution.requirement.digest,
            "policy_digest": resolution.policy_digest,
            "catalog_digest": resolution.catalog_digest,
            "requirement_json": _requirement_json(resolution.requirement),
            "report_json": {
                "candidates": [
                    {
                        "driver_id": candidate.driver_id,
                        "isolation_granted": candidate.isolation_granted.value,
                        "config_digest": candidate.config_digest,
                    }
                    for candidate in resolution.candidates
                ],
                "rejected": [
                    {
                        "driver_id": rejection.driver_id,
                        "code": rejection.code.value,
                        "symbol": rejection.symbol,
                        "gate": rejection.gate,
                        "detail": rejection.detail,
                    }
                    for rejection in resolution.rejected
                ],
                "degradations": [
                    {
                        "kind": degradation.kind,
                        "driver_id": degradation.driver_id,
                        "detail": degradation.detail,
                    }
                    for degradation in resolution.degradations
                ],
                "considered": resolution.considered,
            },
        }
    )


def _requirement_json(requirement: Requirement) -> Mapping[str, JsonValue]:
    """The requirement in canonical JSON — the same projection the digest is taken over."""
    return {
        name: _jsonable(getattr(requirement, name))
        for name in (f.name for f in fields(requirement))
        if name != "digest"
    }


def considered_ids(catalog: Catalog) -> Sequence[str]:
    """Every id `resolve()` will consider, in the order it considers them.

    Exposed because DR5's test is `len(candidates) + len(rejected) == len(considered)`
    (04-driver-system.md:1369) and a test that recomputed the denominator from the same loop
    would be asserting agreement rather than value.
    """
    return sorted(catalog.cards)
