"""The `Catalog`: the metadata-only driver index of one run, and the two digests that pin it.

`Catalog` is what discovery produces and what `resolve()` reads. **Installation is not consent**
(04-driver-system.md section 4.8): being in this index makes a driver a *candidate*, nothing more.
It holds one validated `DriverCard` per discovered id, the probe verdict of each, the trust tier
the loader computed for each, and the framework tombstones -- and it holds them as DATA, because
INV-4 makes discovery import-free and every fact `resolve()` filters on therefore has to be
readable without executing a line of the driver's code.

**This module is pure. It does no I/O and it never resolves.** `Catalog.assemble()` is the seam:
`omniweave_core.discovery` performs section 4.3's nine steps -- `entry_points()`, the `*.dist-info`
scan, `OMNIWEAVE_DRIVER_PATH`, `.omniweave/drivers/`, the shipped tombstones, the card cache and
the probe-verdict cache -- and hands the results here to be checked, defaulted and digested.
Splitting it that way is what lets the digests be property-tested over adversarial input without a
filesystem, and it is why `resolve()` (P3, `omniweave_core/drivers/resolve.py`) can be declared pure
over `(Requirement, Catalog, Policy)`: everything it reads is inside those three arguments.

**Two digests, two different jobs, and confusing them is a correctness bug.**

* `validity_key` answers *"is the `driver_card_cache` still good?"* -- sha256 over the sorted
  `(dist-info path, mtime_ns, size)` triples. It costs 1.01 ms for 328 distributions against 2,124
  ms for a `RECORD` scan, which is precisely why the card cache is validated **wholesale** rather
  than per card (section 4.3, step 2). It is re-checked at run start and at no other time.
* `catalog_digest` answers *"is the resolve memo still good?"* -- sha256 over the canonical form of
  the sorted `(id, card_sha256, origin, trust, status)` rows. It **includes `probe_status`**, which
  is the whole point: a probe verdict that moves from `unknown` to `unavailable` changes which
  drivers `resolve()` returns, so it has to invalidate the memo exactly the way an edited card
  does. A digest over the cards alone would let preflight's re-resolution (section 4.7) read a
  stale answer computed before the verdict existed, and the second pass would silently repeat the
  first.

**`trust` is a field here and not on the card** (E13, section 4.2): it is COMPUTED BY THE LOADER
and never self-reported, so `DriverCard` has no `trust` attribute to read. `compute_trust()` below
is that computation, and its five-row table is first-match-wins.

Specified in 04-driver-system.md section 4.7 (the printed declaration and both digest recipes),
section 4.2 (trust), section 4.3 (the build steps and the validity key), section 4.5 (the duplicate
id), section 4.8 (purity and what `policy_digest` covers instead) and section 7.5 (the tombstones
and their licence-digest set); 11-repo-layout.md section 2.6 and section 7.2 (`first_party.toml`).
"""

from __future__ import annotations

import re
import tomllib
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from functools import cache
from importlib import resources
from pathlib import Path
from types import MappingProxyType
from typing import TYPE_CHECKING, Final, Literal, TypeAlias

from omniweave_ports.types import ProbeStatus, TrustTier

from omniweave_core.canonical import sha256_canonical
from omniweave_core.drivers.card import CARD_ORIGINS, CardOrigin, DriverCard, Tombstone
from omniweave_core.errors import ConfigError, InternalError

if TYPE_CHECKING:  # `discovery` imports this module, so a runtime import here is a cycle.
    from omniweave_core.discovery import Discovery

__all__ = [
    "CATALOG_PROBE_STATUSES",
    "FIRST_PARTY_NAME",
    "FIRST_PARTY_SCHEMA",
    "PROBE_UNKNOWN",
    "TRUST_TABLE",
    "UNPINNED_DEGRADATION",
    "Catalog",
    "CatalogProbeStatus",
    "FirstPartyManifest",
    "FirstPartyRow",
    "TrustDecision",
    "compute_catalog_digest",
    "compute_trust",
    "compute_validity_key",
    "first_party_path",
    "read_first_party",
    "tombstone_licence_digests",
]

# A `DriverId` is a `str`. 04-driver-system.md section 4.7 prints `Mapping["DriverId", DriverCard]`,
# a forward reference to a name the plan never declares in code; its grammar's one home is
# `omniweave_core.drivers.card.DRIVER_ID_RE` (section 5.1), and a `TypeAlias` here would be a
# second home for that fact (INV-21). Annotations say `str`, and this comment says which `str`.

CatalogProbeStatus: TypeAlias = Literal["ok", "degraded", "unavailable", "unknown"]
"""The four verdicts `Catalog.probe_status` holds -- 04-driver-system.md section 4.7, verbatim.

`omniweave_ports.types.ProbeStatus` has **three** members, because a `ProbeVerdict` is what
`probe()` returned and a probe that ran returned one of those three. The fourth value is a property
of the CATALOG, not of any verdict: `unknown` means no probe has run for this
`(driver_id, version, card_sha256, env_digest)` yet. `resolve()` treats it as **passing** the probe
filter -- an unprobed driver is a candidate, not a refusal -- and preflight then probes exactly the
candidates whose status is `unknown`, out of process (section 4.7).
"""

PROBE_UNKNOWN: Final = "unknown"
"""The catalog-only fourth verdict. Not a `ProbeStatus`; see `CatalogProbeStatus`."""

CATALOG_PROBE_STATUSES: Final[tuple[str, ...]] = (
    *(status.value for status in ProbeStatus),
    PROBE_UNKNOWN,
)
"""`CatalogProbeStatus`'s domain as a runtime tuple, DERIVED from `ProbeStatus`.

Written as a derivation rather than a second literal so that adding a fourth `ProbeStatus` member
cannot leave a catalog silently unable to carry it: `ProbeStatus` is the authority for the three
verdicts and `PROBE_UNKNOWN` is this module's own addition. A test holds this tuple against the
`Literal` above, which is the one place the two spellings can drift.
"""

UNPINNED_DEGRADATION: Final = "pin"
"""The `Degradation.kind` a `TrustDecision` of `unpinned` carries.

Row 14 of 15-observability.md section 6.3's closed twenty-seven-member register: *"a component
resolved `unpinned` -- an editable or path install absent from the release manifest"*. The literal
lives here so a trust decision can name what the runtime will record; the `Degradation` **type** is
15-observability.md's sole property (charter erratum E15) and is not redeclared here (INV-21). Once
`omniweave_core.observe.degradation` lands, the caller constructs `Degradation(kind=...)` from this
string -- `TrustDecision` carries the string, never a record of a type this module cannot import.
"""

TRUST_TABLE: Final[tuple[tuple[int, str, str], ...]] = (
    (
        1,
        "first_party",
        "origin == entry_point, the distribution is in the release manifest's first-party list, "
        "its dist_sha256 matches the manifest, and it vendors no third-party source",
    ),
    (
        2,
        "vendored",
        "first-party as row 1, and the driver wraps third-party source under vendor/<name>/ "
        "carrying a recorded SHA, LICENSE, NOTICE and a G12 parity test",
    ),
    (
        3,
        "pinned",
        "origin == entry_point, present in omniweave.lock with a matching dist_sha256",
    ),
    (4, "local", "origin in {driver_path, project}"),
    (
        5,
        "unpinned",
        "otherwise -- an installed distribution absent from the lockfile, or one whose "
        "dist_sha256 has drifted, or a checkout with no release manifest at all",
    ),
)
"""04-driver-system.md section 4.2's five-row table, in its printed order, as `(row, tier, when)`.

Carried as data so a reviewer can diff the implementation against the document and so the test
suite can assert one case per row rather than trusting a comment. First-match-wins: the FIRST row
whose condition holds fixes the tier, and no later row can override it.

**Row 1 as this module implements it carries a conjunct the plan's table does not print**, and the
document forces it. As printed, row 2's condition is row 1's condition plus vendoring, so under
literal first-match-wins row 2 is unreachable and `vendored` could never be computed for anything
-- yet the same section states that `vendored` *is* `parse.office.anydoc`'s tier ("`vendored` is
the tier that lets `parse.office.anydoc` be `inproc`-eligible"), and `omniweave-office` is a
first-party distribution that would match row 1 first. The two statements cannot both hold of the
printed table. Row 1 therefore reads "first-party **and vendors nothing**", which makes every row
reachable, keeps each input matching exactly one row, and reproduces the document's own worked
example. If the intent was instead that `vendored` is unreachable, one conjunct changes here and
section 4.2's anydoc sentence is wrong.
"""

FIRST_PARTY_NAME: Final = "first_party.toml"
"""The release manifest's filename inside `omniweave_core/drivers/`. 11-repo-layout.md section 7.2.

GENERATED package data written into `src/` by the build job and `.gitignore`d, so a developer's
checkout does not have it at all. That absence is not a gap: `read_first_party()` returns `None`,
`compute_trust()` returns `unpinned` with the `pin` degradation, and nothing fails.
"""

FIRST_PARTY_SCHEMA: Final = 1
"""The only `schema` value of `first_party.toml` this build reads. 11-repo-layout.md section 7.2.

A manifest from a future release is refused rather than half-read: it is the input to a TRUST
computation, and guessing at a row shape whose meaning has moved is how a trust tier gets granted
on evidence that no longer says what the reader thinks it says.
"""

_HEX64 = re.compile(r"\A[0-9a-f]{64}\Z")
_SHA256_PREFIXED = re.compile(r"\Asha256:[0-9a-f]{64}\Z")
_NO_CARDS: Final[Mapping[str, DriverCard]] = MappingProxyType({})
_NO_STATUS: Final[Mapping[str, str]] = MappingProxyType({})
_NO_TRUST: Final[Mapping[str, TrustTier]] = MappingProxyType({})
_NO_LOCK: Final[Mapping[str, str]] = MappingProxyType({})
_LOCAL_ORIGINS: Final[frozenset[str]] = frozenset({"driver_path", "project"})


def _internal(message: str) -> InternalError:
    """An assembly inconsistency: OUR bug, never the driver's.

    `DriverHostError` is the area class for a card or protocol mismatch, but nothing reaching these
    checks came from a card -- `load_card()` already refused every malformed one. A status for an id
    that is not in the catalog, or a card filed under the wrong key, can only be a defect in the
    caller assembling the index, which is what `InternalError` names (02-architecture.md section
    7.2). `sys.exit` is banned in library code (G8), so this raises and the runner decides.
    """
    return InternalError(
        message,
        fix="ow doctor --deep --render json   # attach the report: this is an omniweave bug",
    )


# --------------------------------------------------------------------------------------------
# The release manifest (11-repo-layout.md section 7.2)
# --------------------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class FirstPartyRow:
    """One `[dist."<name>"]` row of `first_party.toml`.

    `dist_sha256` is the `"sha256:<64 hex>"` form the manifest prints, kept prefixed because that
    is what `omniweave.lock` and `ow drivers verify` also carry and a bare-hex copy here would be a
    third spelling of one fact.

    `vendored` is **not printed in 11-repo-layout.md section 7.2's manifest and is this module's
    addition**, because 04-driver-system.md section 4.2's row 2 needs a fact -- "carries
    third-party source under `vendor/<name>/` at a recorded SHA with LICENSE, NOTICE and a G12
    parity test" -- that no import-free discovery step can observe. `tools/gen_first_party.py`
    reads the source tree and is the only component that can see it, so the generated manifest is
    where it belongs. It defaults to `False`, so a manifest generated before this key existed
    computes `first_party` rather than failing, which is the conservative direction: `vendored` and
    `first_party` are both `inproc`-eligible (section 6.1), so the default cannot widen an
    isolation grant.
    """

    name: str
    version: str
    dist_sha256: str
    vendored: bool = False


@dataclass(frozen=True, slots=True)
class FirstPartyManifest:
    """`first_party.toml` parsed: the release it describes and its thirteen distribution rows.

    **`omniweave-core` has no row and that is the correct answer, not a gap** (11-repo-layout.md
    section 7.2): a manifest that hashes the wheels cannot live inside one of the wheels it hashes,
    and core is the module computing the trust tier, so a row asserting core's own hash would be a
    witness testifying to itself. Core's integrity is covered by release provenance instead.
    """

    schema: int
    release: str
    dists: Mapping[str, FirstPartyRow]


def first_party_path() -> Path | None:
    """Locate `first_party.toml`, or `None` when this install has none.

    Read through `importlib.resources.files()` and never `__file__` or `__path__[0]`
    (11-repo-layout.md section 2.6 rule 1): a zipapp, a `pip install --target` layout and any
    `zipimport`er give a package with no usable filesystem path, and `__path__[0]` then either
    raises or names a directory that does not hold the file.

    Returning `None` rather than raising is rule 2's other half made specific by section 7.2: the
    manifest is generated into `src/` at build time and `.gitignore`d, so **every** workspace
    checkout is the absent case. Making that an error would make `ow --version` fail on the machine
    of every person who works on omniweave.
    """
    candidate = resources.files("omniweave_core.drivers").joinpath(FIRST_PARTY_NAME)
    return Path(str(candidate)) if candidate.is_file() else None


def read_first_party(path: Path | None = None) -> FirstPartyManifest | None:
    """Parse the release manifest. `None` when absent; a named `ConfigError` when unparseable.

    Read at use time and memoised, never at import time (11-repo-layout.md section 2.6 rule 2):
    graphify's `install.py:35-57` states the reason in its own docstring -- a missing or corrupt
    packaged block that crashes module import bricks every command, not just the one that needed
    the file.

    Absent and unparseable are deliberately different. Absence is the developer's ordinary case and
    degrades one trust computation (section 7.2). A file that exists and does not parse is rule 3's
    case: it raises a named `OwError` carrying the command that clears it, never a `KeyError`, a
    `FileNotFoundError` or a silent empty default -- because an empty default here would compute
    `unpinned` for a first-party wheel and read as an attestation failure rather than as a corrupt
    file.
    """
    located = path or first_party_path()
    return None if located is None else _read_first_party(located)


@cache
def _read_first_party(path: Path) -> FirstPartyManifest:
    try:
        raw = tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, tomllib.TOMLDecodeError) as exc:
        raise ConfigError(
            f"{path} is not a readable first-party release manifest: {exc}",
            fix="pip install --force-reinstall omniweave-core",
        ) from exc
    schema = raw.get("schema")
    if schema != FIRST_PARTY_SCHEMA:
        raise ConfigError(
            f"{path} declares schema = {schema!r}; this build reads {FIRST_PARTY_SCHEMA} only, "
            f"and a trust tier is not granted on a row shape it cannot read",
            fix="pip install --upgrade omniweave-core",
        )
    table = raw.get("dist", {})
    if not isinstance(table, dict):
        raise ConfigError(
            f"{path} has a [dist] that is not a table of distributions",
            fix="pip install --force-reinstall omniweave-core",
        )
    rows: dict[str, FirstPartyRow] = {}
    for name, row in sorted(table.items()):
        if not isinstance(row, dict):
            raise ConfigError(
                f"{path}: [dist.{name}] is not a table",
                fix="pip install --force-reinstall omniweave-core",
            )
        digest = str(row.get("dist_sha256", ""))
        if _SHA256_PREFIXED.fullmatch(digest) is None:
            raise ConfigError(
                f"{path}: [dist.{name}] dist_sha256 = {digest!r} is not 'sha256:<64 hex>'",
                fix="pip install --force-reinstall omniweave-core",
            )
        rows[name] = FirstPartyRow(
            name=name,
            version=str(row.get("version", "")),
            dist_sha256=digest,
            vendored=bool(row.get("vendored", False)),
        )
    return FirstPartyManifest(
        schema=FIRST_PARTY_SCHEMA,
        release=str(raw.get("release", "")),
        dists=MappingProxyType(rows),
    )


# --------------------------------------------------------------------------------------------
# Trust (04-driver-system.md section 4.2, erratum E13)
# --------------------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class TrustDecision:
    """A computed `TrustTier` plus the row that produced it and what the run should record.

    `row` is the 1-based index into `TRUST_TABLE` and exists so first-match-wins is TESTABLE: a
    distribution that is both first-party and in the lockfile satisfies rows 1 and 3, and asserting
    only on the tier cannot tell "row 1 won" from "row 3 happened to agree".

    `degradation` is `UNPINNED_DEGRADATION` or the empty string, never a `Degradation` record --
    that type's sole home is 15-observability.md and this module may not construct one.
    """

    tier: TrustTier
    row: int
    reason: str
    degradation: str = ""


def compute_trust(
    *,
    driver_id: str,
    origin: CardOrigin,
    distribution: str = "",
    dist_sha256: str = "",
    manifest: FirstPartyManifest | None = None,
    locked: Mapping[str, str] = _NO_LOCK,
    vendored: bool | None = None,
) -> TrustDecision:
    """Section 4.2's five-row table, first-match-wins. Trust is never read off a card.

    `DriverCard` carries no `trust` field and never will: a card is a third party's assertion about
    itself, and a self-reported trust tier is the one claim that must not be believed (E13). Every
    input here is either the loader's own observation (`origin`) or a file the OPERATOR controls
    (the release manifest shipped inside core, `omniweave.lock`).

    `locked` is `omniweave.lock`'s `[[driver]]` rows projected to `id -> dist_sha256` -- keyed on
    the driver id because that is the lockfile's own primary key (section 5.5) -- and it is passed
    in rather than read here because `resolve()` is pure over `(Requirement, Catalog, Policy)` and
    the lockfile is loaded into `Policy` at startup (section 4.8).

    `vendored` overrides the manifest row's own flag when given; `None` means "use the manifest".

    `unpinned` is **not a rejection by itself**: `require_lock = true` (the shipped default) turns
    it into `NOT_IN_LOCKFILE` at resolve time, and `[drivers] require_lock = false` is the
    operator's own decision to run unpinned code. What this function returns is evidence, not a
    verdict.

    A `tombstone`-origin card never reaches here -- tombstones are not `Catalog.cards` entries and
    have no trust tier -- but the table stays total, so one would fall to row 5 rather than to an
    unhandled branch.
    """
    if origin not in CARD_ORIGINS:
        raise _internal(f"{driver_id}: origin {origin!r} is not one of {sorted(CARD_ORIGINS)}")

    row = None if manifest is None else manifest.dists.get(distribution)
    attested = (
        origin == "entry_point"
        and row is not None
        and bool(dist_sha256)
        and row.dist_sha256 == dist_sha256
    )
    wraps = row.vendored if vendored is None and row is not None else bool(vendored)

    if attested and not wraps:
        return TrustDecision(TrustTier.FIRST_PARTY, 1, _why(1, distribution))
    if attested:
        return TrustDecision(TrustTier.VENDORED, 2, _why(2, distribution))
    if origin == "entry_point" and bool(dist_sha256) and locked.get(driver_id) == dist_sha256:
        return TrustDecision(TrustTier.PINNED, 3, _why(3, distribution))
    if origin in _LOCAL_ORIGINS:
        return TrustDecision(TrustTier.LOCAL, 4, _why(4, distribution))
    absent = "" if manifest is not None else "; this install carries no release manifest"
    return TrustDecision(
        TrustTier.UNPINNED,
        5,
        _why(5, distribution) + absent,
        degradation=UNPINNED_DEGRADATION,
    )


def _why(row: int, distribution: str) -> str:
    """The table row's own printed condition, with the distribution named."""
    condition = TRUST_TABLE[row - 1][2]
    named = f" ({distribution})" if distribution else ""
    return f"section 4.2 row {row}{named}: {condition}"


# --------------------------------------------------------------------------------------------
# The two digests (04-driver-system.md section 4.7)
# --------------------------------------------------------------------------------------------


def compute_validity_key(triples: Iterable[tuple[str, int, int]]) -> str:
    """`sha256(canonical(sorted triples))` over the `(dist-info path, mtime_ns, size)` triples.

    64 bare hex, and the WHOLESALE card-cache key. Wholesale is the point: section 4.3 measures
    the scan at **1.01 ms for 328 distributions** against **2,124 ms** for the `RECORD` scan
    section 4.1 forbids, so validating every `driver_card_cache` row against one digest is three
    orders of magnitude cheaper than validating each row against its own file. It is re-checked at
    run start and at no other time -- a catalog that changed under a plan would make
    `resolution_digest` a lie and would let two units of one run be parsed by different drivers
    with no record of why.

    **The split with `omniweave_core.discovery` is I/O against arithmetic.** Walking `sys.path`
    with `os.scandir` and `stat` is `discovery.dist_info_triples()`; turning what it saw into a
    digest is here, beside the other digest of section 4.7 and beside `Catalog.assemble()`, which
    validates its `validity_key` argument against this shape. One home each, so the two cannot
    drift into two recipes for one key (INV-21).

    Sorted here rather than trusted from the caller because `os.scandir` order is a filesystem
    property: two machines listing one directory in different orders must produce one key. The
    triple is canonicalised rather than joined, so `("ab", 1, 2)` and `("a", 12, 2)` cannot
    collide -- graphrag's `gen_sha512_hash` concatenates without a separator and does.

    **The wholesale key has one blind spot and it is the developer's own workflow** (section 4.3):
    an editable install leaves `dist-info` untouched while the author edits `driver.toml`, so a
    wholesale-valid cache would serve the old card through the whole edit-conform-fix loop. The
    resolution is discovery's, not this function's -- a distribution reached through
    `direct_url.json` with `"editable": true` or through a `.pth` is stat'ed per card regardless.
    """
    rows = sorted([str(path), int(mtime_ns), int(size)] for path, mtime_ns, size in triples)
    return sha256_canonical(rows)


def compute_catalog_digest(
    cards: Mapping[str, DriverCard],
    probe_status: Mapping[str, str],
    trust: Mapping[str, TrustTier],
) -> str:
    """`sha256(canonical(sorted (id, card_sha256, origin, trust, status)))`. 64 bare hex.

    The third component of `resolve()`'s memo key `(requirement_digest, policy_digest,
    catalog_digest)`, and the reason that memo is sound.

    **`status` is in the row on purpose.** A probe verdict moving from `unknown` to `unavailable`
    changes which drivers `resolve()` returns, so it must invalidate the memo the same way an
    edited card does. Section 4.7's preflight loop depends on exactly this: after `resolve()`
    returns, the runtime probes every candidate whose status is `unknown` and re-resolves **once**
    against the refreshed catalog. Without `status` in the digest the second resolution would hit
    the memo and return the first one's answer, the bound of "two resolutions per requirement per
    run" would buy nothing, and an `unavailable` driver would be dispatched to.

    **Tombstones are deliberately absent from the recipe**, and that is not an omission: the
    tombstone digest set is loaded into `Policy` at startup and `policy_digest` covers it (section
    4.8), so a changed tombstone set already moves the memo key through its other component.

    The field order inside each row is the document's, and `sorted()` over the whole list is what
    makes the digest independent of the order discovery happened to walk entry points in -- the
    property a 100x shuffle test asserts, and the one the memo rests on.
    """
    rows = sorted(
        [
            driver_id,
            card.card_sha256,
            card.origin,
            str(trust.get(driver_id, TrustTier.UNPINNED)),
            probe_status.get(driver_id, PROBE_UNKNOWN),
        ]
        for driver_id, card in cards.items()
    )
    return sha256_canonical(rows)


def tombstone_licence_digests(tombstones: Iterable[Tombstone]) -> frozenset[str]:
    """The known-bad-licence seed set: every `licence_sha256` any shipped tombstone carries.

    Section 7.5's second job for a tombstone. `compute_tier()` (P3, `drivers/licence.py`) returns
    `forbidden` for any card whose `[licence.code].licence_sha256` **or**
    `[licence.weights].licence_sha256` is in this set. The lookup is hash-keyed, so it **survives
    renaming**: a third party wrapping the Datalab weights under a different driver id computes
    `forbidden` too, which a denylist of ids cannot do.

    A `frozenset[str]` of at most a few dozen digests, built ONCE with the tombstones at step 5 of
    `Catalog.build()`, so the check costs one set membership test per card and does not grow with
    the roster.
    """
    return frozenset(
        facts.licence_sha256
        for stone in tombstones
        for facts in (stone.licence_code, stone.licence_weights)
        if facts is not None and facts.licence_sha256
    )


# --------------------------------------------------------------------------------------------
# The catalog itself (04-driver-system.md section 4.7)
# --------------------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Catalog:
    """One metadata-only driver index per run, never rebuilt mid-run.

    The first four fields are 04-driver-system.md section 4.7's printed declaration, in its order.
    The last three are additions the same section forces, each recorded here rather than smuggled
    in:

    * **`trust`** -- section 4.7's own `catalog_digest` recipe reads `trust` per driver, and E13
      puts trust on the loader rather than on the card, so `DriverCard` has no such attribute. The
      printed four-field `Catalog` therefore cannot compute its own digest. Section 6.1 needs the
      same fact at policy time (`trust in {first_party, vendored}` is `inproc`'s first conjunct).
    * **`tombstones`** -- section 7.5 builds them at step 5 of `Catalog.build()`, and section 4.8's
      filter order requires `TOMBSTONED` to carry **the quoted reason**, which only the `Tombstone`
      record holds. They are a separate mapping and not entries in `cards` because a tombstone is
      its own grammar, not a `DriverCard` with holes (section 7.5).
    * **`tombstone_licence_digests`** -- section 7.5 says the set is "built once with the
      tombstones", so it is a field and not a property that would rebuild it per card.

    **Never rebuilt mid-run** (section 4.3). A long-running `ow serve` process holds one catalog per
    run and drops it at run end; the validity key is re-checked at run start and nowhere else. A
    driver installed mid-run is invisible until the next run, which is what makes
    `resolution_digest` a fact about the run rather than about when in the run it was computed.
    """

    cards: Mapping[str, DriverCard]
    probe_status: Mapping[str, CatalogProbeStatus]
    validity_key: str
    catalog_digest: str
    trust: Mapping[str, TrustTier]
    tombstones: Mapping[str, Tombstone]
    tombstone_licence_digests: frozenset[str]

    @classmethod
    def assemble(
        cls,
        *,
        validity_key: str,
        cards: Mapping[str, DriverCard] = _NO_CARDS,
        probe_status: Mapping[str, str] = _NO_STATUS,
        trust: Mapping[str, TrustTier] = _NO_TRUST,
        tombstones: Iterable[Tombstone] = (),
    ) -> Catalog:
        """The assembly seam: already-loaded cards, verdicts and tombstones in, one `Catalog` out.

        **This is where discovery hands off.** `omniweave_core.discovery` owns section 4.3's nine
        steps and every byte of I/O in them; this method owns the checking, the defaulting and the
        two digests. The split is what lets the digest properties be tested over adversarial input
        with no filesystem, and it keeps the module `resolve()` reads free of anything that could
        import, spawn or block.

        Defaults, each a rule from the document rather than a convenience:

        * a driver with no `probe_status` entry gets `unknown`, which section 4.7 makes **passing**
          -- an unprobed driver is a candidate, not a refusal;
        * a driver with no `trust` entry gets `unpinned`, which is row 5 of section 4.2's table
          ("otherwise") and the safe direction: `unpinned` is the tier `require_lock` refuses and
          the one that grants no `inproc`.

        Everything else is an error, because it can only be a defect in the caller: a status or a
        trust tier for an id that is not in `cards`, a card filed under a key that is not its own
        id, two tombstones for one id, a verdict outside the four, or a `validity_key` that is not
        a digest. A catalog that quietly dropped a mismatched row would move `catalog_digest`
        without moving anything a reviewer can see.
        """
        if _HEX64.fullmatch(validity_key) is None:
            raise _internal(f"validity_key {validity_key!r} is not 64 lowercase hex characters")
        for driver_id, card in cards.items():
            if card.identity.id != driver_id:
                raise _internal(
                    f"card filed under {driver_id!r} declares [driver] id = {card.identity.id!r}"
                )
        for name, extra in (("probe_status", probe_status), ("trust", trust)):
            unknown = sorted(set(extra) - set(cards))
            if unknown:
                raise _internal(f"{name} names {unknown}, which the catalog has no card for")

        statuses: dict[str, CatalogProbeStatus] = {}
        for driver_id in cards:
            verdict = probe_status.get(driver_id, PROBE_UNKNOWN)
            if verdict not in CATALOG_PROBE_STATUSES:
                raise _internal(
                    f"{driver_id}: probe status {verdict!r} is not one of "
                    f"{list(CATALOG_PROBE_STATUSES)}"
                )
            statuses[driver_id] = verdict  # type: ignore[assignment]

        tiers = {driver_id: trust.get(driver_id, TrustTier.UNPINNED) for driver_id in cards}
        for driver_id, tier in tiers.items():
            if not isinstance(tier, TrustTier):
                raise _internal(f"{driver_id}: trust {tier!r} is not a TrustTier member")

        stones: dict[str, Tombstone] = {}
        for stone in tombstones:
            if stone.id in stones:
                raise _internal(f"two tombstones declare id {stone.id!r}")
            stones[stone.id] = stone

        return cls(
            cards=MappingProxyType(dict(cards)),
            probe_status=MappingProxyType(statuses),
            validity_key=validity_key,
            catalog_digest=compute_catalog_digest(cards, statuses, tiers),
            trust=MappingProxyType(tiers),
            tombstones=MappingProxyType(stones),
            tombstone_licence_digests=tombstone_licence_digests(stones.values()),
        )

    @classmethod
    def build(
        cls,
        discovery: Discovery | None = None,
        *,
        probe_status: Mapping[str, str] = _NO_STATUS,
        manifest: FirstPartyManifest | None = None,
        locked: Mapping[str, str] = _NO_LOCK,
        dist_sha256: Mapping[str, str] = _NO_LOCK,
        resolve: Mapping[str, str] = _NO_LOCK,
    ) -> Catalog:
        """Section 4.3's nine steps, ONCE per run: `discover()`, then trust, then `assemble()`.

        Steps 1-7 are `omniweave_core.discovery.discover()`'s and every byte of I/O in them is
        there. This method owns what discovery declines to: the duplicate-id check (DR3), the
        trust computation (E13), step 8's probe verdicts and step 9's `catalog_digest`.

        Zero-argument by design, because `tools/gate_coldstart.py` times exactly `Catalog.build()`
        in a fresh interpreter and section 4.4's budget table is stated about that call. Every
        argument is an injection point for a caller that already has the fact:

        * `discovery` -- an already-performed pass, so a caller holding a `Discovery` does not
          walk `sys.path` twice.
        * `probe_status` -- step 8's verdict cache, `omniweave_core.probe`'s (W1.6). Absent, every
          driver is `unknown`, which section 4.7 makes **passing**.
        * `manifest`, `locked`, `dist_sha256` -- section 4.2's three trust inputs. `dist_sha256`
          is `{distribution -> "sha256:<64 hex>"}` as `ow drivers verify` recomputes it; nothing
          at P1 produces it, so the default computes `unpinned` for every installed driver and
          `local` for every `driver_path` or `project` one -- which is 11-repo-layout.md section
          7.2's own description of a developer's checkout, not a defect.
        * `resolve` -- `[drivers.resolve]`, the only thing that lets a duplicate id proceed.

        **A duplicate id propagates as `DuplicateDriver` rather than being absorbed** (section
        4.5). Discovery deliberately returns a `tuple` of `DiscoveredCard` and not a mapping, for
        exactly this reason: a dict would drop one of the two silently. Note the open question,
        which is W3.1's to settle: section 4.5 also gives `resolve()` an `ID_COLLISION_UNQUALIFIED`
        rejection, which is only reachable if some catalog was built with the collision still in
        it. Both cannot be true of the same unresolved duplicate, and this implements the raise
        because that is the sentence naming `Registry.register`.

        Both imports are inside the method and not at module scope, and neither placement is
        stylistic. `omniweave_core.discovery` imports THIS module -- for `compute_validity_key`,
        `compute_trust` and `read_first_party` -- so a top-level import here is a cycle. And
        `resolve()`'s purity rests on the module it reads pulling in nothing that performs I/O, so
        the only route from here to a filesystem is a caller explicitly asking for one.
        `import_module` and `__import__` are banned outside `host/` and are not used: these are
        literal import statements, which a grep for the ban finds and a string cannot reach.
        """
        from omniweave_core.discovery import discover  # noqa: PLC0415
        from omniweave_core.registry import Registry  # noqa: PLC0415

        found = discover() if discovery is None else discovery
        registry: Registry[tuple[DriverCard, str]] = Registry(resolve=resolve)
        for entry in found.found:
            if isinstance(entry.card, DriverCard):
                dist = entry.source.dist_name
                registry.register(entry.card.identity.id, (entry.card, dist), distribution=dist)

        cards: dict[str, DriverCard] = {}
        trust: dict[str, TrustTier] = {}
        for driver_id, (card, dist) in registry.items():
            cards[driver_id] = card
            trust[driver_id] = compute_trust(
                driver_id=driver_id,
                origin=card.origin,
                distribution=dist,
                dist_sha256=dist_sha256.get(dist, ""),
                manifest=manifest,
                locked=locked,
            ).tier

        # A verdict for a driver this run cannot see is dropped rather than refused: the probe
        # cache is a per-machine tree that outlives any one environment, so it legitimately holds
        # rows for drivers that have since been uninstalled (section 4.7).
        return cls.assemble(
            validity_key=found.validity_key,
            cards=cards,
            probe_status={
                driver_id: verdict
                for driver_id, verdict in probe_status.items()
                if driver_id in cards
            },
            trust=trust,
            tombstones=found.tombstones,
        )

    def tombstone_for(self, driver_id: str) -> Tombstone | None:
        """The tombstone refusing `driver_id`, or `None`.

        DR22: a removed or forbidden driver resolves to a **quoted reason and a named
        replacement**, never to "unknown driver". `resolve()`'s `TOMBSTONED` rejection reads
        `.reason` and `.replaced_by` off the record this returns.
        """
        return self.tombstones.get(driver_id)
