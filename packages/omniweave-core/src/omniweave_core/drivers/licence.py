"""Licence tiering: the tier a card cannot declare, the ack a relicence voids, and the Grant that
cannot exist without a `dpa_ref`.

W3.3 (16-roadmap.md:483). The specification is 04-driver-system.md section 7 -- 7.1 the facts and
the computed tier (04:1836-1865), 7.2 the restriction bits (04:1867-1886), 7.3 the
acknowledgement file (04:1888-1919), 7.5 the tombstone seed set (04:2002-2046) -- with
01-principles.md INV-5 and DR15/DR16 (01:205-212), AP-4 (01:1091) for the `Grant`, and
14-security.md section 9.7 (14:1596-1650) for the five properties counsel needs.

WHAT THIS MODULE IS FOR, in one sentence: it turns licence FACTS into a licence VERDICT, and it is
the only place in the framework that does, so that no author, no operator and no config file can
state a tier or a consent the facts do not support.

WHY THE TIER IS COMPUTED AND NEVER DECLARED. 04:712's component row reads "licence tier |
*computed*, never on the card | `compute_tier()` in core", and 04:1838 says why: **an author
cannot mislabel**. The receipt is 01:205-209 -- marker, surya and lift ship a byte-identical
OpenRAIL-M `MODEL_LICENSE` (md5 `e1f69b64dee2f1641a9b1ab12adf24d6`) whose Attachment A clause 2(c)
bars use by anything competing with the licensor, while the top-level `LICENSE` is Apache-2.0 and
mentions weights nowhere. A card that could say `tier = "open"` would be believed. So `tier` is
not in the card grammar at all -- `card.py`'s `LicenceFacts` has no such field and
`_reject_unknown` refuses one -- a *stored* tier anywhere (a lockfile row, an ack row, a posture
report) is a WITNESS compared against this module's output (04:1627), and a disagreement is
`ConfigError`, whose `EXIT` is 1, which is 04:1975-1976's "exit 1 ... a stored tier disagrees with
`compute_tier`".

WHY AN ACK IS BOUND TO THE LICENCE TEXT'S HASH AND NOT TO A BOOLEAN. 02:1166: `omniweave.acks.toml`
holds "per-driver licence acknowledgements, each bound to a `licence_sha256` and **void when it
changes**", because "a boolean in the main config cannot be void". An upstream relicence is a
silent event; the only signal it leaves is that the bytes of the licence text changed. So the
consent names the digest it was given for, the digest is recomputed from the installed text, and a
difference is `AckStatus.STALE` -- 04:1913's `LICENCE_ACK_STALE` **with the hash diff printed**
(DR16, 00:404). There is deliberately no `expires` on an ack (14:1645): an ack is void when the
text changes and at no other time, because an expiry would make a legal decision lapse silently on
a Tuesday.

WHY THE SEED SET IS HASH-KEYED. 04:2016-2020: `compute_tier` returns `forbidden` for any card
whose `[licence.code].licence_sha256` **or** `[licence.weights].licence_sha256` matches a shipped
tombstone's, and that is hash-keyed so it **survives renaming** -- a third party wrapping the
Datalab weights under any driver id computes `forbidden` too. 04:2020 records that this one
mechanism ABSORBS the two separate licence-denylist mechanisms D4 carried, both struck, and
16-roadmap.md:483 states the consolidation as the reason W3.3 is 2 ew: "the separate denylist and
`weights_licence_md5` are STRUCK, so this is one mechanism rather than two that can disagree".
Nothing here builds a second denylist, and nothing here stores an md5 of a weights licence.

WHERE THE SEED SET COMES FROM, AND WHY `seeds` IS A REQUIRED ARGUMENT. 04:2022-2024: the lookup is
"a `frozenset[str]` of at most a few dozen digests, built once with the tombstones at step 5 of
`Catalog.build()`". `resolve()` is pure and reads that set out of `Policy` rather than off the disk
(04:1911, 04:2661), so this module never reads a file to find its seeds either:
`seeds_from_tombstones()` builds a `LicenceSeeds` from already-loaded `Tombstone` records and
`compute_tier` takes it keyword-only **with no default**. A default of "no seeds" would be AP-4's
shape exactly -- "the mechanism exists, the audit finds it, and it has never once run" (01:1091) --
because a caller who forgot the argument would get a `forbidden` check that silently never fires.

WHAT THIS MODULE DOES NOT DO. It compares no fact against configuration. `[licence] allow_tiers`,
`[licence] jurisdiction` and `[licence] fields_of_use` (02:1194, 04:1915-1919) are *selectors*
applied by the INV-5 gate order inside `resolve()` (W3.1) and by the posture report (E12, 04:1921);
putting them here would give one refusal two homes. The split is: facts -> tier and text -> ack
validity are this module's; tier -> allowed and exclusion -> local refusal are the caller's.
Stamping `restriction_bits` onto every row is the runner's (04:1873, INV-16), but the fact-to-bit
map that stamping reads is here, because it is a reading of the same ten facts the tier is and a
second reading of them elsewhere could disagree with this one.

THE FIVE DEPARTURES FROM THE PLAN AS WRITTEN, each reported rather than smoothed:

1. **`compute_tier`'s printed signature cannot express its own first rule.** 04:1843 declares
   `compute_tier(code, weights) -> LicenceTier`, and 04:1844-1845's first rule reads "forbidden <=
   id in the shipped tombstone set OR licence_sha256 (code or weights) matches a shipped
   tombstone's". Neither an id nor the tombstone set is a parameter, and 05:2525 writes a third
   spelling, `compute_tier(card)`. Resolved by keeping the plan's two positional parameters and
   adding the keyword-only `seeds`, and by putting the ID half of rule 1 in `tier_from_card()`,
   the one entry point that HAS an id. A tombstoned id normally never reaches a `DriverCard` --
   `load_card()` branches on `[tombstone]` before any driver-card validation (04:2004) -- so that
   arm bites exactly the case that motivates it: a third party shipping a real card under a
   vetoed id.
2. **Two of the twelve `Restriction` bits do not raise the tier.** 04:1869-1870 allocates twelve
   codes; 04:1847-1850's `restricted` rule reads ten facts and reads neither
   `attribution_per_output` nor `no_model_training`. So a driver whose only licence fact is
   "attribution required per output" computes `open`, needs no ack, still stamps a bit onto every
   block it produces, and can still refuse the OUT direction (04:1873-1876). That is the plan's
   arithmetic and it is implemented as written -- `restrictions_of()` returns all twelve,
   `tier_of()` reads the ten -- but the two sets are not one set, and a reader who assumed
   `restricted == (bits != 0)` would be wrong.
3. **"The fact and its bit differ by casing and nothing else" is false for four of the twelve.**
   04:1871-1875 says the fact-to-bit map "special-cases nothing", and `card.py`'s `LicenceFacts`
   docstring repeats it. But `revenue_gate_usd` -> `REVENUE_GATE` is a rename, `redistribution !=
   "allowed"` -> `NO_REDISTRIBUTION` is a derivation from a string, and `spdx in COPYLEFT_NETWORK`
   / `spdx in COPYLEFT_STRONG` -> `COPYLEFT_NETWORK` / `COPYLEFT_STRONG` are two more. Eight of the
   twelve are casing-identical. `_BIT_FROM_FACT` writes the mapping out so the departure is
   visible instead of inferred; a `getattr(facts, member.name.lower())` loop would have raised
   `AttributeError` on four of twelve, and is exactly the code that made the claim look true.
4. **`COPYLEFT_NETWORK` and `COPYLEFT_STRONG` have no enumeration site.** 04:1850 reads them as
   sets of SPDX ids and no document lists their members. What the plan does say is used and nothing
   more: 14:1620-1621 fixes AGPL as `COPYLEFT_NETWORK` ("AGPL's section 13 is the *network*
   clause ... using the wrong bit would let an artefact carrying it pass a policy that filters the
   other"), 04:2031 groups "AGPL-3.0 / SSPL / GPL-3.0 code" as `restricted`, and 14:1476-1478
   spells the SPDX ids. LGPL is deliberately in neither set: 14:1478 denies it as a *dependency* of
   omniweave, which is a different mechanism with a different owner (`tools/licences.toml`,
   14:1650), and calling weak copyleft "strong" here would invent a licence reading. An LGPL driver
   therefore computes `open` unless another fact bites, and that is reported, not hidden.
5. **Membership is over the whole `spdx` string, as 04:1850 writes it.** An SPDX *expression*
   (`"MIT OR AGPL-3.0-or-later"`) matches neither set and computes `open`. Parsing expressions
   would be a licence reading this module is not entitled to make; the hole is real and belongs to
   the `licence` conformance suite (04:2076) and to `ow drivers check --posture`.

CORE PURITY. Standard library plus `omniweave_ports` (INV-2, D1): `hashlib`, `tomllib`, `datetime`.
No clock is read here -- `Grant.is_active()` takes `now` as a parameter, because clocks and ids are
parameters framework-wide -- no file is opened, and no `subprocess`, RNG or `sys.exit` appears.
Nothing in this module is imported by `omniweave_core/__init__.py`, so G17's nine lazy names are
untouched.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import tomllib
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from enum import StrEnum
from types import MappingProxyType
from typing import Final

from omniweave_ports.types import LicenceTier, Restriction

from omniweave_core.drivers.card import DriverCard, LicenceFacts, Tombstone
from omniweave_core.errors import ConfigError

__all__ = [
    "ACK_ROW_KEYS",
    "ACK_ROW_REQUIRED",
    "ACK_STALE_CODE",
    "ACK_VERSIONS_SUPPORTED",
    "COPYLEFT_NETWORK",
    "COPYLEFT_STRONG",
    "GRANT_MANIFEST_FIELDS",
    "REDISTRIBUTION_ALLOWED",
    "SHA256_PREFIX",
    "TIER_ORDER",
    "Ack",
    "AckSet",
    "AckStatus",
    "AckVerdict",
    "AckWhich",
    "Grant",
    "LicenceSeeds",
    "TierMismatch",
    "check_ack",
    "compute_tier",
    "licence_sha256",
    "load_acks",
    "require_computed_tier",
    "restriction_bits",
    "restrictions_of",
    "seeds_from_tombstones",
    "stored_tier_mismatch",
    "tier_from_card",
    "tier_of",
    "tier_rank",
    "tier_reasons",
]


# --------------------------------------------------------------------------------------------
# 1. The lattice, the vocabularies, and the one digest spelling.
# --------------------------------------------------------------------------------------------

TIER_ORDER: Final[tuple[LicenceTier, ...]] = (
    LicenceTier.OPEN,
    LicenceTier.RESTRICTED,
    LicenceTier.COMMERCIAL,
    LicenceTier.FORBIDDEN,
)
"""`open < restricted < commercial < forbidden`, verbatim from 04:1856.

It exists because `LicenceTier` is a `StrEnum` and `max()` over a `StrEnum` compares *strings*:
`max("open", "forbidden")` is `"open"`, which would return the permissive tier for a forbidden
card -- the single worst wrong answer this module could give. Every comparison goes through
`tier_rank()`.

`commercial` sorting ABOVE `restricted` is the plan's and is not obvious: a copyleft licence an
operator may knowingly accept for an internal deployment is less of an obstacle than one requiring
a purchased credential nobody has purchased. 04:2029-2036's table is the reasoning, and 04:2807
records that release 1 ships no `commercial`-tier driver at all, so the tier is specified and its
only test is a synthetic card (Q12, 04:2804-2810)."""

REDISTRIBUTION_ALLOWED: Final[str] = "allowed"
"""The one `redistribution` value that does NOT contribute a restriction (04:1849).

The vocabulary itself is `card.py`'s `REDISTRIBUTIONS`, and this module reads the fact rather than
the vocabulary -- `!= "allowed"` is what 04:1849 writes, so a value the card grammar admits and
this module has never heard of counts as a restriction rather than as `open`."""

SHA256_PREFIX: Final[str] = "sha256:"
"""How a licence digest is written wherever a human diffs one: `licence_sha256 = "sha256:37a680..."`
(04:1902, 14:1614). The same spelling `card.py`'s `card_sha256()` uses over card bytes; cache-key
digests are bare hex and these are not cache keys."""

COPYLEFT_NETWORK: Final[frozenset[str]] = frozenset(
    {
        "AGPL-3.0",
        "AGPL-3.0-only",
        "AGPL-3.0-or-later",
        "SSPL-1.0",
    }
)
"""The network-copyleft SPDX ids of 04:1850's `spdx in COPYLEFT_NETWORK`.

Every member is a licence the plan names in a copyleft context: 14:1620-1621 fixes AGPL here rather
than in `COPYLEFT_STRONG` ("AGPL's section 13 is the *network* clause"), 04:2031 lists "AGPL-3.0 /
SSPL / GPL-3.0 code" as `restricted`, and 14:1476-1478 spells the ids. SSPL is here and not in
`COPYLEFT_STRONG` for the same reason AGPL is: its trigger is offering the software as a service.
The bare `AGPL-3.0` spelling is deprecated in SPDX and is carried anyway, because 14:1621 and
04:2031 both write it and a card that writes what the plan writes must not compute `open`.

The consequence, and the reason these are two sets rather than one COPYLEFT: 10:2343-2349 makes
`ow serve --http` REFUSE at listener start when any enabled driver's tier carries
`copyleft_network`, while accepting the same driver for a local run. A single bit would let an
artefact pass a policy that filters the other."""

COPYLEFT_STRONG: Final[frozenset[str]] = frozenset(
    {
        "GPL-2.0",
        "GPL-2.0-only",
        "GPL-2.0-or-later",
        "GPL-3.0",
        "GPL-3.0-only",
        "GPL-3.0-or-later",
    }
)
"""The strong-copyleft SPDX ids of 04:1850's `spdx in COPYLEFT_STRONG`.

GPL-3.0 is `restricted` by 04:2031, `GPL-3.0-only` is the recorded fact on the shipped
`parse.doc.omniparse` tombstone, and 14:1477 spells the four dashed forms. LGPL is deliberately not
here: see departure 4. The two suffix-less spellings are carried for the same reason as in
`COPYLEFT_NETWORK`."""


# --------------------------------------------------------------------------------------------
# 2. The restriction bits (04-driver-system.md section 7.2).
# --------------------------------------------------------------------------------------------

_BIT_FROM_FACT: Final[Mapping[str, Restriction]] = MappingProxyType(
    {
        "output_share_alike": Restriction.OUTPUT_SHARE_ALIKE,
        "competitor_bar": Restriction.COMPETITOR_BAR,
        "territory_excluded": Restriction.TERRITORY_EXCLUDED,
        "field_of_use_excluded": Restriction.FIELD_OF_USE_EXCLUDED,
        "revenue_gate_usd": Restriction.REVENUE_GATE,
        "mau_gate": Restriction.MAU_GATE,
        "no_model_training": Restriction.NO_MODEL_TRAINING,
        "attribution_per_output": Restriction.ATTRIBUTION_PER_OUTPUT,
        "remote_kill_switch": Restriction.REMOTE_KILL_SWITCH,
    }
)
"""The nine bits whose fact is a truth test on a single `LicenceFacts` field.

Written out rather than derived from `Restriction.__members__`, because the derivation the plan
claims -- 04:1871-1875, the fact-to-bit map "special-cases nothing" -- does not hold. Eight of the
nine rows here ARE casing-identical; the ninth (`revenue_gate_usd` -> `REVENUE_GATE`) is a rename,
and the remaining three of the twelve codes have no boolean fact at all and are handled below. See
departure 3 in the module docstring."""

_BITS_OUTSIDE_THE_TIER: Final[frozenset[Restriction]] = frozenset(
    {Restriction.ATTRIBUTION_PER_OUTPUT, Restriction.NO_MODEL_TRAINING}
)
"""The two allocated bits 04:1847-1850's `restricted` rule does not read.

Subtracted rather than left out of `_BIT_FROM_FACT`, so both readings of the twelve codes stay
available and the difference between them is one named constant a reader can find (departure 2).
04:1957-1961's posture report prints `no_model_training` and `attribution_per_output` as
consequences of the ENABLED SET, which is why they are bits at all."""


def restrictions_of(facts: LicenceFacts) -> frozenset[Restriction]:
    """Every `Restriction` one `[licence.*]` table carries (04:1867-1886).

    All twelve codes are reachable from here, which is NOT the same set as the ten facts
    `tier_of()` reads: `attribution_per_output` and `no_model_training` contribute a bit and do not
    raise the tier. A caller asking "is this restricted" must ask `tier_of()` and never
    `bool(restrictions_of(...))`.

    A non-zero `revenue_gate_usd` or `mau_gate` is a restriction and a zero one is not, which is
    why the shipped Datalab tombstones write `revenue_gate_usd = 0`: clause 2(c) has no revenue
    threshold at all, so recording $5,000,000 there would record the *other* clause (04:2039-2044,
    01:205-209). Those cards are `forbidden` through `competitor_bar` and the seed set, never
    through a gate.
    """
    found: set[Restriction] = set()
    for field_name, bit in _BIT_FROM_FACT.items():
        if getattr(facts, field_name):
            found.add(bit)
    if facts.redistribution != REDISTRIBUTION_ALLOWED:
        found.add(Restriction.NO_REDISTRIBUTION)
    if facts.spdx in COPYLEFT_NETWORK:
        found.add(Restriction.COPYLEFT_NETWORK)
    if facts.spdx in COPYLEFT_STRONG:
        found.add(Restriction.COPYLEFT_STRONG)
    return frozenset(found)


def restriction_bits(facts: LicenceFacts) -> int:
    """`restriction_bits` for one table: the OR of `1 << r.value` over `restrictions_of()`.

    The runner stamps this onto every block, segment, entity, mention, edge, claim, asset and
    artefact the producing card makes (04:1873-1876, INV-16, DR17). It is computed here rather than
    there because it is a reading of the same facts the tier is, and 04:1877-1881 is why the bit
    must travel at all: `marker/MODEL_LICENSE:39` applies the licence "to the Output and any
    derivatives", so no care at install time helps if the bit does not reach the artefact.
    """
    bits = 0
    for restriction in restrictions_of(facts):
        bits |= restriction.bit
    return bits


# --------------------------------------------------------------------------------------------
# 3. The seed set (04-driver-system.md section 7.5).
# --------------------------------------------------------------------------------------------


def _normalise_digest(value: str) -> str:
    """A licence digest, comparable.

    Lower-cased **only** when it is a `sha256:` digest, whose hex has one canonical casing. The
    other legal form is an explicitly-marked `unresolved:` seed (`tools/gate_tombstones.py`'s
    `SEED_RE`), and three of the shipped six carry one because the Datalab `MODEL_LICENSE` is not
    in this repository and never will be (11:2499 layer 1) -- so the plan prints its md5 and elides
    its sha256. `unresolved:omniparse/LICENSE` contains a PATH, and lower-casing a path silently
    changes it, which is why this is not one `.lower()` over everything.
    """
    text = value.strip()
    if text.lower().startswith(SHA256_PREFIX):
        return text.lower()
    return text


@dataclass(frozen=True, slots=True)
class LicenceSeeds:
    """The shipped refusal set as `compute_tier()` reads it: digests and ids (04:2016-2024).

    Both halves of 04:1844-1845's `forbidden` rule live here. `digests` is the hash-keyed half --
    "at most a few dozen digests", built once at step 5 of `Catalog.build()` -- and is what makes
    the refusal survive a rename. `ids` is the id-keyed half, which normally never fires because
    `load_card()` branches on `[tombstone]` before any driver-card validation (04:2004), and fires
    exactly when a third party ships a real card under a vetoed id.

    **An empty digest can never be a member.** `seeds_from_tombstones()` drops one and `seeded()`
    refuses to compare one, which is two guards for one hazard on purpose:
    `LicenceFacts.licence_sha256` defaults to `""`, four of the six shipped tombstones write a
    `[licence.code]` table with no digest in it, and a single `""` in this set would make every
    card that omits its own digest `forbidden`. `tools/gate_tombstones.py`'s `SEED_RE` refuses to
    ship such a card; these two guards mean a hand-built set cannot do it either.
    """

    digests: frozenset[str] = frozenset()
    ids: frozenset[str] = frozenset()

    def __post_init__(self) -> None:
        """Normalise and drop the empty digest, whoever built the set.

        `seeds_from_tombstones()` already does both, so this fires for a set built by hand -- a
        test, a `Policy` assembled from a lockfile, a posture report. Doing it in only one of the
        two places was the bug this replaces: the LOOKUP normalises its input, so a stored
        `SHA256:AB...` would never have matched anything and the refusal would have been silently
        absent, which is AP-4's shape and the exact failure a seed set exists to prevent.
        """
        clean = frozenset(_normalise_digest(digest) for digest in self.digests if digest.strip())
        if clean != self.digests:
            object.__setattr__(self, "digests", clean)

    def seeded(self, facts: LicenceFacts | None) -> bool:
        """Does this table's `licence_sha256` match a shipped tombstone's? (04:2016)"""
        if facts is None or not facts.licence_sha256:
            return False
        return _normalise_digest(facts.licence_sha256) in self.digests

    def tombstoned(self, driver: str) -> bool:
        """Is this driver id itself vetoed? The id half of 04:1844."""
        return driver in self.ids


def seeds_from_tombstones(tombstones: Iterable[Tombstone]) -> LicenceSeeds:
    """Build the seed set from already-loaded tombstones -- `Catalog.build()`'s step 5 (04:2022).

    Over `Tombstone` records and not over a directory, because `resolve()` is pure and reads this
    set out of `Policy` rather than off the disk (04:1911, 04:2661). Both licence tables of every
    tombstone are read: 04:2016 says code **or** weights, and two of the six shipped tombstones
    ship no `[licence.weights]` at all, so a code-side-only reading would drop them -- while
    11:2503's "each carrying ... a `[licence.weights].licence_sha256`" is true of four of the six
    and not of all six, which `tools/gate_tombstones.py`'s `seeds()` already reports.

    An empty `licence_sha256` is dropped rather than refused: `[licence.code] spdx = "Apache-2.0"`
    with no digest is exactly what the Datalab cards write, and it is a recorded fact about the
    trap (their top-level LICENSE is permissive) rather than a defective seed.
    """
    digests: set[str] = set()
    ids: set[str] = set()
    for stone in tombstones:
        ids.add(stone.id)
        for table in (stone.licence_code, stone.licence_weights):
            if table is None or not table.licence_sha256:
                continue
            digests.add(_normalise_digest(table.licence_sha256))
    return LicenceSeeds(digests=frozenset(digests), ids=frozenset(ids))


# --------------------------------------------------------------------------------------------
# 4. compute_tier (04-driver-system.md section 7.1).
# --------------------------------------------------------------------------------------------


def tier_rank(tier: LicenceTier) -> int:
    """Position in `TIER_ORDER`. The only ordering of `LicenceTier` in the framework."""
    return TIER_ORDER.index(tier)


def tier_of(facts: LicenceFacts, *, seeds: LicenceSeeds) -> LicenceTier:
    """One `[licence.*]` table's tier -- 04:1844-1851's ladder, in its stated order.

    The order is the specification and not an optimisation: `forbidden` is tested first because a
    card can carry both a seeded weights digest and `requires_credential`, and a forbidden card
    must not be reported as merely commercial. `open` is the fall-through, so a fact this module
    has never heard of cannot silently raise the tier -- which is the correct direction for that
    failure, because a NEW restriction arrives as a card-grammar change (`card.py` refuses an
    unknown `[licence.*]` key outright and bumps `card_schema`) rather than as a value here.
    """
    if seeds.seeded(facts):
        return LicenceTier.FORBIDDEN
    if facts.requires_credential:
        return LicenceTier.COMMERCIAL
    if restrictions_of(facts) - _BITS_OUTSIDE_THE_TIER:
        return LicenceTier.RESTRICTED
    return LicenceTier.OPEN


def compute_tier(
    code: LicenceFacts,
    weights: LicenceFacts | None = None,
    *,
    seeds: LicenceSeeds,
) -> LicenceTier:
    """The tier of one card's licence facts. **04:1843's function, and the only one.**

    `max(tier(code), tier(weights))` on `open < restricted < commercial < forbidden`, "because the
    weakest link governs" (04:1855-1856). `weights` is `None` when a driver ships no weights --
    04:1856-1858: `[licence.weights]` is **omitted entirely** rather than emptied, because an empty
    table is not the same statement as an absent one, and `card.py` refuses the empty one.

    Args:
        code: `[licence.code]`, which every driver card has -- it is required at load.
        weights: `[licence.weights]`, or `None` when the driver ships no weights.
        seeds: the shipped tombstone seed set. Keyword-only and **required, with no default**: see
            the module docstring's departure 1 and its AP-4 reasoning. A caller with no catalog in
            hand passes `LicenceSeeds()` explicitly and thereby states, in code a reviewer can
            grep for, that this computation had no refusal set behind it.

    Returns:
        The higher of the two tiers, on `TIER_ORDER`.

    This function does not read the driver id, so the id half of 04:1844 is `tier_from_card()`'s.
    It performs no I/O and reads no clock: 04:1842 calls it PURE and `resolve()` depends on that.
    """
    tier = tier_of(code, seeds=seeds)
    if weights is not None:
        tier = max(tier, tier_of(weights, seeds=seeds), key=tier_rank)
    return tier


def tier_from_card(card: DriverCard, *, seeds: LicenceSeeds) -> LicenceTier:
    """`compute_tier()` plus the id half of 04:1844 -- the whole of the `forbidden` rule.

    05:2525 spells this call `compute_tier(card)`; the name differs here so that the plan's printed
    two-parameter signature keeps its own name (INV-21: one fact, one spelling, and the fact
    `compute_tier` states is "these FACTS imply this tier").

    A vetoed id reaching a `DriverCard` is not the normal path -- `load_card()` returns a
    `Tombstone` for the shipped six -- so this arm exists for the case 04:2018 names: someone
    else's card, under a vetoed id, with licence facts of their own choosing.
    """
    if seeds.tombstoned(card.identity.id):
        return LicenceTier.FORBIDDEN
    return compute_tier(card.licence_code, card.licence_weights, seeds=seeds)


def tier_reasons(
    code: LicenceFacts,
    weights: LicenceFacts | None = None,
    *,
    seeds: LicenceSeeds,
    driver: str = "",
) -> tuple[str, ...]:
    """Why the tier is what it is, one clause per line, for a refusal a human has to act on.

    04:1973 requires a refusal to name "the driver, the clause refs and the exact command that
    would resolve it", and 04:1839's `ow drivers check` has to print the DIFFERENCE between a
    stored tier and this computation. A bare enum member cannot be argued with, so every producer
    that fired is named, together with the `clause_refs` the card recorded -- which is the point of
    that field: `parse.page.surya`'s reason cites `Attachment A 2(c) at MODEL_LICENSE:58`, and a
    refusal printing `forbidden` alone would send the operator to read a licence they already paid
    someone to read.

    An empty result means `open` by fall-through, which is the one tier with no producer.
    """
    lines: list[str] = []
    if driver and seeds.tombstoned(driver):
        lines.append(f"{driver} is itself a shipped tombstone (04-driver-system.md section 10.4)")
    for label, facts in (("code", code), ("weights", weights)):
        if facts is None:
            continue
        lines.extend(f"[licence.{label}] {reason}" for reason in _facts_reasons(facts, seeds))
    return tuple(lines)


def _facts_reasons(facts: LicenceFacts, seeds: LicenceSeeds) -> tuple[str, ...]:
    """The clauses one table contributes, in the ladder's order."""
    lines: list[str] = []
    if seeds.seeded(facts):
        lines.append(
            f"licence_sha256 {facts.licence_sha256} matches a shipped tombstone's -> forbidden"
        )
    if facts.requires_credential:
        lines.append("requires_credential -> commercial")
    carried = restrictions_of(facts)
    lines.extend(
        f"{bit.name.lower()} -> restricted"
        for bit in sorted(carried - _BITS_OUTSIDE_THE_TIER, key=lambda bit: bit.value)
    )
    lines.extend(
        f"{bit.name.lower()} -> a restriction bit that does not raise the tier"
        for bit in sorted(carried & _BITS_OUTSIDE_THE_TIER, key=lambda bit: bit.value)
    )
    if facts.spdx:
        lines.append(f"spdx {facts.spdx}")
    lines.extend(f"clause {ref}" for ref in facts.clause_refs)
    return tuple(lines)


# --------------------------------------------------------------------------------------------
# 5. A stored tier is a witness (04:1839, 04:1627, 04:1975-1976).
# --------------------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class TierMismatch:
    """A recorded tier that disagrees with the computed one. DR15's whole surface.

    `stored` is whatever wrote a tier down -- an `omniweave.lock` row (04:1627, "the lock is a
    witness rather than an authority"), an `omniweave.acks.toml` row's `tier` key (04:1904), a
    posture report a release pipeline asserted on. None of them is authoritative and all of them
    are comparable, which is why this type carries a `source` string rather than three variants.
    """

    driver: str
    stored: str
    computed: LicenceTier
    source: str
    reasons: tuple[str, ...] = ()

    @property
    def message(self) -> str:
        """The refusal, with the difference printed."""
        head = (
            f"{self.driver}: {self.source} records licence tier {self.stored!r} and the facts "
            f"compute {self.computed.value!r}. The card carries FACTS and the tier is COMPUTED "
            f"(04-driver-system.md:1838); a recorded tier is a witness, never an authority"
        )
        if not self.reasons:
            return head
        return head + "\n" + "\n".join(f"  {reason}" for reason in self.reasons)


def stored_tier_mismatch(
    *,
    driver: str,
    stored: str,
    computed: LicenceTier,
    source: str,
    reasons: tuple[str, ...] = (),
) -> TierMismatch | None:
    """`None` when the witness agrees, a `TierMismatch` when it does not.

    Takes `computed` rather than recomputing it, deliberately. A function that both derived the
    tier and compared it against a witness would let a test call one thing and assert agreement
    between two halves of one computation; here the computation is `compute_tier()`'s, pinned in
    the tests against literal tiers, and the comparison is this function's, pinned against literal
    disagreements. Two subjects, two tests, and no place for the two to agree by construction.

    An unknown `stored` spelling is a mismatch and not an error: `tier = "permissive"` in a
    hand-edited ack row is precisely the mislabelling DR15 exists to catch, and refusing to compare
    it would turn a caught mislabel into an unread exception.
    """
    if stored == computed.value:
        return None
    return TierMismatch(
        driver=driver, stored=stored, computed=computed, source=source, reasons=reasons
    )


def require_computed_tier(
    *,
    driver: str,
    stored: str,
    computed: LicenceTier,
    source: str,
    reasons: tuple[str, ...] = (),
) -> None:
    """Raise `ConfigError` when a witness disagrees. 04:1975-1976's **exit 1**.

    `ConfigError.EXIT` is 1 and `PolicyRefusal.EXIT` is 6, and 04:1972-1976 assigns those two
    numbers to exactly these two conditions -- a policy refusal is exit 6, and "a stored tier
    disagrees with `compute_tier`" is exit 1. So the exit code is not a constant this module
    invents: it is the exception class, through the mechanism 10-interfaces.md section 9.3 already
    fixes, which is why nothing here passes an exit code as an argument.

    A mismatch is a `ConfigError` rather than a `PolicyRefusal` for a reason worth stating: the
    driver may be perfectly permissible. What is wrong is the FILE, and telling an operator that
    their licence policy refused a driver when their lockfile is merely stale would send them to
    counsel instead of to `ow drivers check`.
    """
    found = stored_tier_mismatch(
        driver=driver, stored=stored, computed=computed, source=source, reasons=reasons
    )
    if found is not None:
        raise ConfigError(found.message, fix="ow drivers check --posture")


# --------------------------------------------------------------------------------------------
# 6. The acknowledgement file (04-driver-system.md section 7.3, erratum E11).
# --------------------------------------------------------------------------------------------

ACK_VERSIONS_SUPPORTED: Final[frozenset[int]] = frozenset({1})
"""Every `ack_version` this build reads. 04:1898 writes `ack_version = 1`.

A file from a newer grammar is refused rather than read leniently, for the same reason
`card_schema` is the first key `load_card()` reads: a consent record misread is a consent recorded
that nobody gave.

Membership is tested against a REAL `int`, and `bool` is excluded by hand, because Python makes
`True in frozenset({1})` and `1.0 in frozenset({1})` both true. `ack_version = true` would
otherwise have loaded as version 1 -- a boolean admitted by the version key of the one file whose
whole reason for existing is that "a boolean in the main config cannot be void" (02:1166). The
parsed value is then FORWARDED into `AckSet.ack_version` rather than re-typed as a literal, so the
field records what the operator wrote and can be wrong about it."""

ACK_STALE_CODE: Final[str] = "LICENCE_ACK_STALE"
"""The label a stale-ack refusal prints. 04:1913, 01:211, 00:404, 11:2502.

**It is a label here and a `RejectCode` member in `resolve()`**: 04:1565 lists `LICENCE_ACK_STALE`
among the resolve-policy reject codes and W3.1 owns that enum. One token, two mechanical needs --
the message a human reads and the typed rejection a `Resolution` carries. This constant exists so
the message half has a single spelling; `resolve()` should build its member from it rather than
re-typing the string, and if it does not, the two spellings are a defect to report rather than a
style difference."""

ACK_ROW_REQUIRED: Final[tuple[str, ...]] = (
    "driver",
    "licence_sha256",
    "which",
    "tier",
    "acknowledged_by",
    "acknowledged_at",
)
"""The six keys an `[[ack]]` row may not omit.

04:1900-1908 prints eight. These six are the DECISION -- who accepted what, for which artefact,
against which text, and when -- while `restrictions` records the bits as of that reading and `note`
is prose. Requiring `restrictions` would make a `restricted` tier arising from `redistribution !=
"allowed"` alone unacknowledgeable; requiring `note` would make a decision unwritable without a
sentence about it."""

ACK_ROW_KEYS: Final[tuple[str, ...]] = (*ACK_ROW_REQUIRED, "restrictions", "note")
"""The complete legal key set of an `[[ack]]` row (04:1900-1908). A row carrying anything else is
refused: an ack file is read by counsel, and a key nobody validates is a key nobody reads.

There is no `expires`, and that absence is load-bearing (14:1645-1648): an ack is void when the
licence text changes and at no other time, because an expiry date "would make a legal decision
lapse silently on a Tuesday"."""


class AckWhich(StrEnum):
    """Which licensed artefact one ack row covers -- `code | weights` (04:1903).

    One row per licensed artefact, because the two texts are two grants: the Datalab trap is
    exactly a permissive code licence over restrictive weights (01:205-209), so an operator who
    accepted the code licence has not thereby accepted the weights licence.
    """

    CODE = "code"
    WEIGHTS = "weights"


class AckStatus(StrEnum):
    """What an ack lookup found. Four values, and the fourth is not a synonym for the first.

    `NOT_REQUIRED` is a computed tier that needs no ack at all -- 04:1890 binds the requirement to
    `restricted` and to nothing else, so an `open` driver with no row is correct while a
    `restricted` one with no row is `MISSING`. Reporting both as `OK` would make "the ack set is
    empty" indistinguishable from "every ack is valid", which is the shape of an assertion over an
    empty collection: it passes and proves nothing.
    """

    OK = "ok"
    MISSING = "missing"
    STALE = "stale"
    NOT_REQUIRED = "not_required"


@dataclass(frozen=True, slots=True)
class Ack:
    """One `[[ack]]` row: an operator's consent, bound to a licence text's digest.

    Every field is the operator's own statement except `licence_sha256`, which is the binding.
    `tier` is a WITNESS -- the tier as computed on the day the decision was made -- and is compared
    through `stored_tier_mismatch()`, never trusted: an ack row is a file a human edits, and a row
    claiming `tier = "open"` for a card whose facts compute `forbidden` is DR15's mislabel arriving
    through the consent file instead of through the card.
    """

    driver: str
    licence_sha256: str
    which: AckWhich
    tier: str
    acknowledged_by: str
    acknowledged_at: str
    restrictions: tuple[str, ...] = ()
    note: str = ""


@dataclass(frozen=True, slots=True)
class AckSet:
    """The loaded `omniweave.acks.toml`, keyed by `(driver, which)`.

    04:1911 loads this into `Policy` at startup so `resolve()` reads it as an argument rather than
    touching the filesystem, and `policy_digest` covers it. Keyed by the pair because 04:1914 makes
    two rows for one `(driver, which)` a hard error at load -- "an ack is a decision, and two
    decisions is none" -- so the mapping IS that uniqueness constraint rather than a check
    alongside it.
    """

    rows: Mapping[tuple[str, AckWhich], Ack] = MappingProxyType({})
    ack_version: int = 1

    def get(self, driver: str, which: AckWhich) -> Ack | None:
        """The row for one licensed artefact, or `None`."""
        return self.rows.get((driver, which))


def licence_sha256(raw: bytes) -> str:
    """`sha256:` over the RAW BYTES of a licence text -- the value an ack is bound to.

    Over bytes, because the thing being identified is a legal text and a normalising digest would
    make a whitespace-only relicence invisible. That is the same choice `card.py`'s `card_sha256()`
    makes and for the same reason: what is pinned is what was read.

    Deliberately not `identity.content_digest()`, which is the document model's `ow128` over
    normalised text and children, and not `config_digest()`, which is bare hex over canonical JSON.
    A licence digest is a value a human diffs in version control (04:1902), so it carries its
    algorithm.
    """
    return SHA256_PREFIX + hashlib.sha256(raw).hexdigest()


def load_acks(raw: bytes, *, source: str) -> AckSet:
    """Parse `omniweave.acks.toml` (04:1896-1909). **The only constructor of `AckSet`.**

    Args:
        raw: the file's bytes.
        source: the path, named in every refusal.

    Returns:
        The loaded set. A file with `ack_version = 1` and no rows is legal and is the shipped
        default: `[licence] allow_tiers = ["open"]` means a fresh install needs no ack at all
        (04:1915).

    Raises:
        ConfigError: an unreadable file, an `ack_version` that is not an integer this build reads,
            a missing or unknown key, a
            `which` outside its vocabulary, a restriction name that is not a `Restriction`, or two
            rows for one `(driver, which)`. Exit 1 in every case, because 04:1975 makes "the
            configuration itself is unreadable" exit 1, and a consent file that does not parse is
            exactly that.

    `tier` is NOT validated against `LicenceTier` even though restriction names are validated, and
    the asymmetry is deliberate. A restriction name outside the vocabulary cannot be compared to
    anything, so it is malformed. An unknown tier spelling CAN be compared -- and
    `stored_tier_mismatch()` reports it as the mislabel it is, naming the computed tier beside it.
    Refusing to load it would replace a specific, actionable licence finding with a parse error.
    """
    try:
        doc = tomllib.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, tomllib.TOMLDecodeError) as exc:
        raise ConfigError(
            f"{source}: not readable as UTF-8 TOML -- {exc}",
            fix="ow drivers ack --check",
        ) from exc
    version = doc.get("ack_version")
    if (
        not isinstance(version, int)
        or isinstance(version, bool)
        or version not in ACK_VERSIONS_SUPPORTED
    ):
        raise ConfigError(
            f"{source}: ack_version is {version!r}; this build reads "
            f"{sorted(ACK_VERSIONS_SUPPORTED)}. A consent record misread is a consent nobody "
            f"gave, so a newer grammar is refused rather than read leniently",
            fix="ow drivers ack --check",
        )
    unknown = sorted(set(doc) - {"ack_version", "ack"})
    if unknown:
        raise ConfigError(
            f"{source}: unknown top-level key(s) {unknown}; the file holds `ack_version` and "
            f"`[[ack]]` rows and nothing else (04-driver-system.md:1896-1909)",
            fix="ow drivers ack --check",
        )
    rows: dict[tuple[str, AckWhich], Ack] = {}
    for index, table in enumerate(_ack_tables(doc, source)):
        ack = _ack_row(table, source=source, index=index)
        key = (ack.driver, ack.which)
        if key in rows:
            raise ConfigError(
                f"{source}: two [[ack]] rows for ({ack.driver!r}, {ack.which.value!r}). An ack is "
                f"a decision and two decisions is none (04-driver-system.md:1914)",
                fix="ow drivers ack --check",
            )
        rows[key] = ack
    return AckSet(rows=MappingProxyType(dict(rows)), ack_version=version)


def _ack_tables(doc: Mapping[str, object], source: str) -> tuple[Mapping[str, object], ...]:
    """The `[[ack]]` array, or `()`. Absent is legal; a `[ack]` table instead of `[[ack]]` is not.

    The distinction is worth a refusal rather than a coercion: TOML's single-bracket form would
    parse one row into a table and silently drop the array semantics, and a consent FILE that
    holds one decision where the operator wrote three is the failure this whole section exists to
    prevent.
    """
    value = doc.get("ack", [])
    if not isinstance(value, list) or any(not isinstance(row, dict) for row in value):
        raise ConfigError(
            f"{source}: `ack` must be an array of tables, each written `[[ack]]`",
            fix="ow drivers ack --check",
        )
    return tuple(value)


def _ack_row(table: Mapping[str, object], *, source: str, index: int) -> Ack:
    """One `[[ack]]` row, validated key by key. The row number is 1-based, as a human counts."""
    where = f"{source}: [[ack]] #{index + 1}"
    unknown = sorted(set(table) - set(ACK_ROW_KEYS))
    if unknown:
        raise ConfigError(
            f"{where}: unknown key(s) {unknown}. The legal set is {list(ACK_ROW_KEYS)}; there is "
            f"deliberately no `expires`, because an ack is void when the licence text changes and "
            f"at no other time (14-security.md:1645)",
            fix="ow drivers ack --check",
        )
    missing = [key for key in ACK_ROW_REQUIRED if key not in table]
    if missing:
        raise ConfigError(f"{where}: missing required key(s) {missing}", fix="ow drivers ack")
    for key in ACK_ROW_REQUIRED:
        value = table[key]
        if not isinstance(value, str) or not value.strip():
            raise ConfigError(
                f"{where}: {key} must be a non-empty string, not {value!r}",
                fix="ow drivers ack --check",
            )
    which = str(table["which"])
    try:
        member = AckWhich(which)
    except ValueError as exc:
        raise ConfigError(
            f"{where}: which is {which!r}; one row per licensed artefact, so it is "
            f"{[value.value for value in AckWhich]} (04-driver-system.md:1903)",
            fix="ow drivers ack --check",
        ) from exc
    return Ack(
        driver=str(table["driver"]),
        licence_sha256=str(table["licence_sha256"]),
        which=member,
        tier=str(table["tier"]),
        acknowledged_by=str(table["acknowledged_by"]),
        acknowledged_at=str(table["acknowledged_at"]),
        restrictions=_ack_restrictions(table.get("restrictions", []), where),
        note=_ack_note(table.get("note", ""), where),
    )


def _ack_restrictions(value: object, where: str) -> tuple[str, ...]:
    """`restrictions = ["copyleft_network"]` -- names from the closed `Restriction` vocabulary.

    Validated against `Restriction` because 14:1620-1621 turns on the difference between two of
    them: an ack naming `copyleft_strong` where AGPL's section 13 applies "would let an artefact
    carrying it pass a policy that filters the other". A name outside the vocabulary is refused
    rather than kept as prose.

    It is NOT required to equal the computed restriction set. The binding is `licence_sha256`
    (04:1890), and requiring the two to agree would fail an operator's record of what they read on
    a card fact that moved without the text moving -- which the digest does not catch, and should
    not, because the operator's consent was given to the TEXT.
    """
    if not isinstance(value, list) or any(not isinstance(name, str) for name in value):
        raise ConfigError(
            f"{where}: restrictions must be an array of strings", fix="ow drivers ack --check"
        )
    legal = {member.name.lower() for member in Restriction}
    unknown = sorted(set(value) - legal)
    if unknown:
        raise ConfigError(
            f"{where}: restriction(s) {unknown} are not `Restriction` codes. The vocabulary is "
            f"closed at 32 reserved codes with twelve defined (04-driver-system.md:1869)",
            fix="ow drivers ack --check",
        )
    return tuple(str(name) for name in value)


def _ack_note(value: object, where: str) -> str:
    """The prose. Optional, and a non-string is a mistake worth naming rather than coercing."""
    if not isinstance(value, str):
        raise ConfigError(f"{where}: note must be a string", fix="ow drivers ack --check")
    return value


@dataclass(frozen=True, slots=True)
class AckVerdict:
    """What an ack lookup decided, with the hash diff a stale one has to print.

    04:1913 makes "mutating the licence file in a test and asserting `LICENCE_ACK_STALE` **with the
    hash diff printed**" a required test, and DR16 is why: the operator has to be able to SEE that
    the text moved, not merely be told their consent is void. So both digests are carried in full
    -- a truncated digest in a refusal is a digest nobody can check -- together with the index at
    which they first differ, because two sha256 values differ everywhere and the eye needs a
    pointer to where.
    """

    status: AckStatus
    driver: str
    which: AckWhich
    acknowledged: str = ""
    installed: str = ""

    @property
    def valid(self) -> bool:
        """Does the ack gate open? `OK` and `NOT_REQUIRED`, and nothing else.

        This says nothing about whether the driver may run: a `forbidden` card needs no ack and may
        never run either way (04:2033). Whether a tier is permitted is `[licence] allow_tiers`'s
        question and the caller's.
        """
        return self.status in (AckStatus.OK, AckStatus.NOT_REQUIRED)

    @property
    def first_difference(self) -> int:
        """The index at which the two digests first differ, or `-1` when they do not.

        A shared prefix is not a curiosity: a relicence that changes one byte of the text moves the
        digest completely, so a pair sharing three or four leading characters is the ordinary case,
        and an operator comparing them by eye stops reading once the prefix matches.
        """
        pairs = zip(self.acknowledged, self.installed, strict=False)
        for index, (left, right) in enumerate(pairs):
            if left != right:
                return index
        if len(self.acknowledged) == len(self.installed):
            return -1
        return min(len(self.acknowledged), len(self.installed))

    @property
    def message(self) -> str:
        """The refusal, naming the driver, the artefact, both digests and the command."""
        if self.status is AckStatus.STALE:
            return (
                f"{ACK_STALE_CODE} {self.driver} ({self.which.value}): the acknowledged licence "
                f"text is not the installed one, so the acknowledgement is void "
                f"(04-driver-system.md:1890)\n"
                f"  acknowledged  {self.acknowledged}\n"
                f"  installed     {self.installed}\n"
                f"  first differ  index {self.first_difference}\n"
                f"  fix           ow drivers ack {self.driver}"
            )
        if self.status is AckStatus.MISSING:
            return (
                f"LICENCE_ACK_MISSING {self.driver} ({self.which.value}): the computed tier is "
                f"restricted and omniweave.acks.toml holds no row for it. Installation is not "
                f"consent (INV-5)\n"
                f"  installed     {self.installed}\n"
                f"  fix           ow drivers ack {self.driver}"
            )
        return f"{self.status.value} {self.driver} ({self.which.value})"


def check_ack(
    *,
    driver: str,
    which: AckWhich,
    tier: LicenceTier,
    installed: str,
    acks: AckSet,
) -> AckVerdict:
    """Is this licensed artefact acknowledged against the text that is actually installed?

    Args:
        driver: the driver id an ack row would name.
        which: `code` or `weights` -- one row per licensed artefact (04:1903).
        tier: the tier `compute_tier()` gave THIS artefact's facts. An ack is required for
            `restricted` and for nothing else (04:1890); `forbidden` has no ack path at all
            (04:2033, "there is no configuration in which omniweave may run it") and `open` and
            `commercial` are gated by `allow_tiers` alone.
        installed: `licence_sha256()` over the licence text as installed.
        acks: the loaded set, passed in because `resolve()` may not read a file (04:1911).

    Returns:
        An `AckVerdict`. `STALE` is 04:1913's `LICENCE_ACK_STALE` and its `message` prints the hash
        diff; `MISSING` is 04:1565's `LICENCE_ACK_MISSING`.

    A non-`restricted` artefact returns `NOT_REQUIRED` and not `OK`: nothing about an ack can help a
    `forbidden` one, and answering "valid" for a tier that can never run would be true and
    misleading.
    """
    if tier is not LicenceTier.RESTRICTED:
        return AckVerdict(
            status=AckStatus.NOT_REQUIRED, driver=driver, which=which, installed=installed
        )
    row = acks.get(driver, which)
    if row is None:
        return AckVerdict(status=AckStatus.MISSING, driver=driver, which=which, installed=installed)
    if _normalise_digest(row.licence_sha256) != _normalise_digest(installed):
        return AckVerdict(
            status=AckStatus.STALE,
            driver=driver,
            which=which,
            acknowledged=row.licence_sha256,
            installed=installed,
        )
    return AckVerdict(
        status=AckStatus.OK,
        driver=driver,
        which=which,
        acknowledged=row.licence_sha256,
        installed=installed,
    )


# --------------------------------------------------------------------------------------------
# 7. The Grant (01-principles.md AP-4 at 01:1091; glossary "Grant"; 14-security.md section 5.2).
# --------------------------------------------------------------------------------------------

GRANT_MANIFEST_FIELDS: Final[tuple[str, ...]] = (
    "grant_id",
    "dpa_ref",
    "approver",
    "expires",
    "scope",
)
"""Every field of a `Grant` reaches the run manifest, and `dpa_ref` is why the type exists.

14:890 lists "`Grant` ids and `dpa_ref`s" among a run manifest's contents and 01:1091 requires the
`dpa_ref` "printed in every affected run manifest". The whole record is printed rather than those
two fields, because a manifest carrying a grant id and a DPA reference without the approver or the
expiry names the decision and hides who made it and until when.

A literal tuple rather than `dataclasses.fields(Grant)`, because a manifest's field list is a
published contract (14:890, 15:2022) and deriving it from the type would let a field rename change
the audit's column names silently. The tests assert the two agree, where a divergence is a finding
rather than a rename."""


@dataclass(frozen=True, slots=True)
class Grant:
    """A site-layer authorisation for egress, carrying a **required** `dpa_ref`. AP-4's answer.

    AP-4 (01:1091) is the anti-pattern "the safety mechanism whose default disables it", and its
    receipts are docling's `max_file_size = sys.maxsize`, olmocr building a `PdfFilter` behind an
    `--apply_filter` that is `action="store_true"`, and marker's `--use_llm` shipping page images to
    Gemini by default. Its verdict is the sentence this class is built against: **"the mechanism
    exists, the audit finds it, and it has never once run."** A required field enforced by a
    validator on some code path is exactly that failure, because the path that skips the validator
    is the path that ships. So `dpa_ref` has no default and `__post_init__` refuses a blank one: a
    `Grant` without a DPA reference cannot be brought into existence on any code path, including
    `dataclasses.replace()`.

    `dpa_ref` is **deliberately unvalidated beyond being present** (14:806-807): "validating it
    would imply omniweave can tell whether your data-processing agreement covers this, which it
    cannot. Naming it forces someone to write down which agreement they are relying on." So the
    only check is that a human wrote something.

    `bytes_egress` defaults to 0 (05:1290, 08:2275), so the first hosted escalation is refused
    until a Grant exists, and `route_decision.grant_id` is non-null **iff** `bytes_egress > 0`
    (05:2820). This type is the RECORD; admitting work against it is `admit()`'s step 3 (05:2526)
    and is not here. Its scope semantics are 05's too: glossary "Grant" says a grant authorises "a
    scoped corpus", the shape of that scope is not specified anywhere, and inventing a matcher here
    would put a policy decision in a value type.

    No clock is read. `expires` is the string as written and `is_active()` takes `now` as a
    parameter, because a value type that consulted the wall clock would make every test of it a
    test of the day it ran.
    """

    grant_id: str
    dpa_ref: str
    approver: str
    expires: str
    scope: str

    def __post_init__(self) -> None:
        """Refuse a Grant that names no agreement, approver, expiry or scope.

        `dpa_ref` is checked first and named first because it is the field AP-4 is about; the other
        four are checked because a grant with an empty approver is a decision nobody made.
        `ValueError` and not `PolicyRefusal`: no operator policy is being refused here, a caller is
        being told it constructed an invalid value.
        """
        if not self.dpa_ref.strip():
            raise ValueError(
                "a Grant names the data-processing agreement it relies on: dpa_ref is required and "
                "is deliberately unvalidated beyond being present (01-principles.md AP-4, "
                "14-security.md:806). It is printed in the run manifest of every document that "
                "egressed"
            )
        for field_name in ("grant_id", "approver", "expires", "scope"):
            if not str(getattr(self, field_name)).strip():
                raise ValueError(f"a Grant names its {field_name}; it is empty")
        self.expires_at()

    def expires_at(self) -> dt.datetime:
        """`expires` as a timezone-aware instant, or `ValueError`.

        Parsed at construction so a malformed expiry is a construction failure rather than a
        surprise at the moment a run asks whether it may egress. Timezone-aware is required for the
        reason the DTZ lint family exists: a naive expiry names a different instant on every machine
        in a fleet, and a fleet is exactly what a site-layer grant covers.
        """
        parsed = dt.datetime.fromisoformat(self.expires)
        if parsed.tzinfo is None:
            raise ValueError(
                f"a Grant's expires must carry a timezone offset: {self.expires!r} is naive, so it "
                f"names a different instant on every machine the grant covers"
            )
        return parsed

    def is_active(self, now: dt.datetime) -> bool:
        """Is this grant unexpired at `now`? The clock is the caller's, always."""
        if now.tzinfo is None:
            raise ValueError("is_active takes a timezone-aware instant; clocks are parameters")
        return now < self.expires_at()

    def manifest_row(self) -> Mapping[str, str]:
        """The record printed in the run manifest of every document this grant covers.

        Every field, `dpa_ref` included and `dpa_ref` first among the reasons this method exists
        (01:1091, 14:890). Redaction is NOT applied here: 13:981 makes a *cassette* replace a
        `dpa_ref` with its sha256 because a cassette is a fixture, and doing that here would redact
        the manifest the audit reads.
        """
        return MappingProxyType({name: str(getattr(self, name)) for name in GRANT_MANIFEST_FIELDS})
