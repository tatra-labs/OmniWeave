"""`ow drivers check | explain | verify | list` — W3.1's four verbs, before the CLI exists.

`packages/omniweave/src/omniweave/` is a bare skeleton: the run loop is P4's and the CLI is P7's
(16-roadmap.md section 10), so none of the four verbs W3.1 names has a place to live yet. The
standing pattern is ledger D25, applied four times now — `ow schema emit` -> `tools/schemagen.py`
at P1, `ow store verify` -> `store/verify.py` + `tools/gate_crash.py`, `ow test crash-matrix` ->
`store/crashmatrix.py` + `tools/gate_crash.py`, `ow eval perf` -> `store/inspect.py` +
`tools/measure_store.py`: **the library function lives in the package and a `tools/` script
drives it**, and P7 wraps the script's `main()` when the CLI arrives.
`tools/gate_crash.py`'s docstring is the worked example of saying so.

`omniweave_core.drivers.resolve` is the library half. This is the driver.

## What this script adds that the library may not do

Everything here is I/O, and every piece of it is a thing `resolve()` is pure *because* it does not
do (04-driver-system.md:1376-1381):

* it **reads the filesystem** — `omniweave.lock`, `omniweave.acks.toml`, a directory of
  `driver.toml` files, or the installed distributions through `omniweave_core.discovery`;
* it **assembles the `Policy`** those files describe, which is exactly 04:1378-1381's "the ack
  set, the lockfile id set and the tombstone digest set are loaded into `Policy` at startup";
* it **prints**, and `T20` bans `print` in library code for the reason 10-interfaces.md gives: a
  library that writes to a stream cannot be embedded. `tools/` is not library code —
  `tools/gate_semgrep.py:26-37` takes that reading for itself in as many words.

It does **not** activate a driver. `activate()` is "the only site that imports a card's
entrypoint" (02-architecture.md:237) and it is not here, so `ow drivers list` over a hostile wheel
imports nothing (INV-4, G11).

## The four verbs

* **`list`** — the roster, in the shape 04-driver-system.md:2344 prints: id, version, tier, cost
  class, isolation, attested, and whether the id is in `[drivers] enabled`. The `NOT ENABLED`
  column is the point of the verb: INV-5 makes `[drivers] enabled` the only activation gate, and
  it is the one gate `resolve()` does not apply (:1360), so nothing but this listing tells an
  operator that an installed, attested, locked driver will never run.
* **`check`** — the licence posture, and **exit 1 on a tier mismatch**. 02-architecture.md:1194:
  "The tier itself is computed by `compute_tier`, never declared, and `ow drivers check` exits
  non-zero on a mismatch". 04:1626 says which mismatch: "the loader still recomputes both and
  `ow drivers check` exits non-zero when a recorded tier disagrees with `compute_tier` (DR15), so
  the lock is a witness rather than an authority". `--posture` adds section 7.4's report mode.
* **`verify`** — 04:1620: "`ow drivers verify` recomputes `dist_sha256` and `card_sha256` from
  what is installed and exits non-zero on any drift". `card_sha256`'s recipe is printed
  (section 2.8, and `card.py` implements it), so that half is a real check. **`dist_sha256` has
  no printed recipe** — 04:1131-1133 says only that "a distribution digest is a hash over
  installed files, which is the `RECORD` walk section 4.1 forbids", and forbids it on the
  discovery path rather than defining it. So a locked `dist_sha256` is reported UNVERIFIED with
  that reason rather than compared against a recipe this script invented. Reported as a finding.
* **`explain`** — one `resolve()` call and its report, printed in the shape
  18-api-sketch.md:2156-2160 does: the code, its `codes.toml` numeric and symbol, the gate that
  refused, and the detail. `--gates` prints the gate order itself, which is the observable fact
  04-driver-system.md:1340 makes load-bearing.

## Exit codes

`0` the verb ran and found nothing wrong; `1` the verb ran and found something wrong — a tier
mismatch, a card digest drift, a zero-candidate resolution under `--require-candidate`; `2` the
verb did not run: a bad argument, an unreadable lockfile, a card that will not parse when one was
named explicitly. `1` and `2` are distinguished because CI treats both as failure and a human
needs to know which (`tools/gate_crash.py`'s wording, and the same reason).

Specified in 02-architecture.md section 2 row 13 and section 3.3's config table (`[drivers]`,
`[licence]`); 04-driver-system.md sections 4.8, 5.3, 5.5, 7.1-7.4 and 9 step 5;
16-roadmap.md:481; 18-api-sketch.md sections 5.3 and 5.4.
"""

from __future__ import annotations

import argparse
import ctypes.util
import os
import platform
import shutil
import sys
import tomllib
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Final, TextIO

from omniweave_core import discovery
from omniweave_core.drivers.card import (
    DriverCard,
    Tombstone,
    card_sha256,
    load_card,
    read_card_bytes,
)
from omniweave_core.drivers.catalog import Catalog, compute_trust
from omniweave_core.drivers.licence import (
    AckSet,
    compute_tier,
    load_acks,
    restriction_bits,
    restrictions_of,
    seeds_from_tombstones,
    stored_tier_mismatch,
)
from omniweave_core.drivers.resolve import (
    GATE_ORDER,
    Policy,
    Requirement,
    Resolution,
    resolution_report,
    resolve,
)
from omniweave_core.errors import DriverHostError, NotFoundError, explain
from omniweave_ports.types import ArtifactKind, CostClass, ProbeEnv

__all__ = [
    "EXIT_CLEAN",
    "EXIT_FAIL",
    "EXIT_NOT_RUN",
    "LOCK_FILENAME",
    "LockRow",
    "Workspace",
    "main",
    "verb_check",
    "verb_explain",
    "verb_list",
    "verb_verify",
]

EXIT_CLEAN: Final = 0
EXIT_FAIL: Final = 1
EXIT_NOT_RUN: Final = 2

LOCK_FILENAME: Final = "omniweave.lock"
ACKS_FILENAME: Final = "omniweave.acks.toml"
CARD_FILENAME: Final = "driver.toml"

DIST_DIGEST_UNVERIFIABLE: Final = (
    "dist_sha256 UNVERIFIED: 04-driver-system.md:1131-1133 says only that a distribution digest "
    "is 'a hash over installed files, which is the RECORD walk section 4.1 forbids' and prints "
    "no recipe. Comparing a locked value against a recipe this script invented would report "
    "agreement with itself"
)
"""Why `verify` checks one of the two digests 04:1620 names and reports the other.

Stated as a message rather than as a comment because the operator running `ow drivers verify` is
the person who needs to know which half of the promise held."""


# --------------------------------------------------------------------------------------------
# 1. The files a Policy is assembled from
# --------------------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class LockRow:
    """One `[[driver]]` row of `omniweave.lock` — 04-driver-system.md:1602-1620's shape.

    `tier` and `restriction_bits` are recorded in the lock deliberately: "a licence posture is a
    reviewable diff in version control, not a value recomputed at runtime and forgotten" (:1624).
    Both are WITNESSES, which is what makes `check` a comparison rather than a read.
    """

    id: str
    version: str
    dist: str
    dist_sha256: str
    card_sha256: str
    tier: str
    restriction_bits: int


@dataclass(frozen=True, slots=True)
class Workspace:
    """The files this run read, and the `Policy` they describe.

    Assembled once per invocation. `Policy` is frozen and `policy_digest` covers every field, so
    two runs over the same tree resolve identically — which is what makes `explain`'s printed
    `resolution_digest` worth printing at all.
    """

    root: Path
    cards: Mapping[str, DriverCard]
    tombstones: tuple[Tombstone, ...]
    lock: Mapping[str, LockRow]
    acks: AckSet
    catalog: Catalog
    policy: Policy


def read_lock(path: Path) -> dict[str, LockRow]:
    """Parse `omniweave.lock`. An absent file is an empty lock and not an error.

    A fresh checkout has no lockfile, and `[drivers] require_lock = true` then makes every id
    `NOT_IN_LOCKFILE` — which is INV-5 working correctly and exactly what `explain` should print,
    not a reason for this script to refuse to run.
    """
    if not path.is_file():
        return {}
    parsed = tomllib.loads(path.read_text(encoding="utf-8"))
    rows: dict[str, LockRow] = {}
    for raw in parsed.get("driver", ()):
        row = LockRow(
            id=str(raw["id"]),
            version=str(raw.get("version", "")),
            dist=str(raw.get("dist", "")),
            dist_sha256=str(raw.get("dist_sha256", "")),
            card_sha256=str(raw.get("card_sha256", "")),
            tier=str(raw.get("tier", "")),
            restriction_bits=int(raw.get("restriction_bits", 0)),
        )
        if row.id in rows:
            raise ValueError(
                f"{path}: two [[driver]] rows for {row.id!r}; a lock row is a decision and two "
                f"decisions is none"
            )
        rows[row.id] = row
    return rows


def read_acks(path: Path) -> AckSet:
    """Parse `omniweave.acks.toml`, or return the empty set when the file is absent.

    An empty set is the shipped default: `[licence] allow_tiers = ["open"]` means a fresh install
    needs no ack at all (04-driver-system.md:1915).
    """
    if not path.is_file():
        return AckSet()
    return load_acks(path.read_bytes(), source=str(path))


def load_cards_from(directory: Path) -> tuple[dict[str, DriverCard], list[Tombstone]]:
    """Every `driver.toml` under `directory`, loaded without importing anything.

    The `--cards` path exists so `check`, `verify` and `explain` are runnable against a tree of
    cards rather than only against installed wheels: a conformance author's card is on disk before
    it is ever installed (04-driver-system.md section 9 step 4 runs `ow conform` before step 5
    installs), and a gate that could only read `site-packages` could not read it.
    """
    cards: dict[str, DriverCard] = {}
    tombstones: list[Tombstone] = []
    for path in sorted(directory.rglob(CARD_FILENAME)):
        loaded = load_card(read_card_bytes(path), origin="project", source=str(path))
        if isinstance(loaded, Tombstone):
            tombstones.append(loaded)
            continue
        if loaded.identity.id in cards:
            raise ValueError(
                f"{path}: {loaded.identity.id!r} is already declared by "
                f"{cards[loaded.identity.id].source}; a duplicate id never wins silently (DR3)"
            )
        cards[loaded.identity.id] = loaded
    return cards, tombstones


def host_env() -> ProbeEnv:
    """This host, as the `[hardware]` gate reads it.

    Deliberately assembled HERE and not inside the package: `ProbeEnv` carries `sys.platform`,
    `platform.machine()` and `shutil.which()` results, and every one of those is an ambient input
    a library may not read (02-architecture.md:392). `resolve()` takes it as `Policy.host_env`.

    `gpu_present` is `ctypes.util.find_library("cuda") is not None` and never an import of a
    framework (04-driver-system.md:148), and `vram_gb` is `0.0` when unknown for the same reason,
    which means a card declaring `vram_gb_min` is `HARDWARE_ABSENT` on every host this script can
    speak for. That is the honest answer: this script does not load a vendor driver library.
    """
    binaries = {
        name: shutil.which(name)
        for name in sorted({"tesseract", "pdftoppm", "libreoffice", "node"})
    }
    return ProbeEnv(
        platform=sys.platform,
        machine=platform.machine(),
        python=(sys.version_info.major, sys.version_info.minor),
        which=binaries,
        gpu_present=ctypes.util.find_library("cuda") is not None,
        vram_gb=0.0,
        offline=False,
    )


def workspace(args: argparse.Namespace) -> Workspace:
    """Read the tree and assemble the `Catalog` and the `Policy`."""
    root = args.root.resolve()
    if args.cards is not None:
        cards, tombstone_list = load_cards_from(args.cards.resolve())
        validity = card_sha256(str(args.cards.resolve()).encode("utf-8"))
    else:
        found = discovery.discover(env=dict(os.environ), project_root=root)
        cards = {card.identity.id: card for card in found.cards}
        tombstone_list = list(found.tombstones)
        validity = found.validity_key or card_sha256(b"no-distribution-scan")
    tombstones = tuple(tombstone_list)
    lock = read_lock(root / LOCK_FILENAME)
    acks = read_acks(root / ACKS_FILENAME)
    locked_digests = {row.id: row.dist_sha256 for row in lock.values()}
    trust = {
        driver_id: compute_trust(
            driver_id=driver_id,
            origin=card.origin,
            locked=locked_digests,
        ).tier
        for driver_id, card in cards.items()
    }
    catalog = Catalog.assemble(
        validity_key=validity.removeprefix("sha256:"),
        cards=cards,
        trust=trust,
        tombstones=tombstones,
    )
    policy = Policy(
        allow_tiers=frozenset(args.allow_tiers),
        jurisdiction=args.jurisdiction,
        fields_of_use=frozenset(args.fields_of_use),
        acks=acks,
        licence_seeds=seeds_from_tombstones(tombstones),
        locked_ids=frozenset(lock),
        require_lock=args.require_lock,
        allow_unattested=args.allow_unattested,
        allow_cost_classes=frozenset(args.allow_cost_classes),
        enabled=frozenset(args.enabled),
        host_env=host_env(),
    )
    return Workspace(
        root=root,
        cards=cards,
        tombstones=tombstones,
        lock=lock,
        acks=acks,
        catalog=catalog,
        policy=policy,
    )


# --------------------------------------------------------------------------------------------
# 2. list
# --------------------------------------------------------------------------------------------


def _port_string(card: DriverCard) -> str:
    """`parse/1` — the card's Port and major, as `[driver] port` spells it."""
    return f"{card.identity.port.value}/{card.identity.port_major}"


def verb_list(space: Workspace, emit: TextIO, *, port: str | None) -> int:
    """The roster, in the columns 04-driver-system.md:2344 prints.

    The last column is why the verb exists. An id absent from `[drivers] enabled` can never run,
    `resolve()` does not say so (:1360 puts that gate outside it), and `ow doctor` FAILS on a
    driver a policy rule names but `enabled` omits (02-architecture.md:1192). Printing
    `NOT ENABLED` beside `attested` and `locked` is the only place the three facts meet.

    Exit is always `0`: a listing reports and never judges.
    """
    say = _sayer(emit)
    seeds = space.policy.licence_seeds
    rows = [
        card
        for _, card in sorted(space.cards.items())
        if port is None or _port_string(card) == port
    ]
    if not rows:
        say("no driver cards found. --cards <dir> reads a tree; the default reads the environment")
    for card in rows:
        tier = compute_tier(card.licence_code, card.licence_weights, seeds=seeds)
        cost = (card.cost_model.cost_class if card.cost_model else CostClass.FREE).value
        enabled = "enabled" if card.identity.id in space.policy.enabled else "NOT ENABLED"
        say(
            f"{card.identity.id:<28} {card.identity.version:<7} {tier.value:<11} {cost:<14} "
            f"{card.isolation.requires.value:<8} "
            f"{'attested' if card.attested else 'unattested':<10} "
            f"{'locked' if card.identity.id in space.lock else 'unlocked':<8} {enabled}"
        )
        if enabled == "NOT ENABLED":
            say(f"{'':<28} ^ add it to omniweave.toml [drivers] enabled  (INV-5)")
    for stone in space.tombstones:
        say(f"{stone.id:<28} {'TOMBSTONED':<7} {stone.reason}")
    return EXIT_CLEAN


# --------------------------------------------------------------------------------------------
# 3. check
# --------------------------------------------------------------------------------------------


def verb_check(space: Workspace, emit: TextIO, *, posture: bool) -> int:
    """Recompute every tier and compare it against the lock's witness. **Exit 1 on a mismatch.**

    02-architecture.md:1194 and 04-driver-system.md:1626 both. The comparison is
    `omniweave_core.drivers.licence.stored_tier_mismatch()`, which takes the computed tier rather
    than recomputing it — so this function calls `compute_tier` once and the comparison has no
    place to agree with itself.

    `restriction_bits` is compared the same way and for the same reason (:1624). A lock row with
    no `tier` at all is not a mismatch: an `ow drivers add` that predates the tier column wrote no
    witness, and reporting an absent witness as a disagreement would send an operator to counsel
    over a stale file.
    """
    say = _sayer(emit)
    seeds = space.policy.licence_seeds
    failures = 0
    compared = 0
    for driver_id, card in sorted(space.cards.items()):
        computed = compute_tier(card.licence_code, card.licence_weights, seeds=seeds)
        row = space.lock.get(driver_id)
        if posture:
            bits = restriction_bits(card.licence_code)
            names = sorted(r.name.lower() for r in restrictions_of(card.licence_code))
            say(f"{driver_id:<28} {computed.value:<11} bits=0x{bits:03x} {names}")
        if row is None or not row.tier:
            continue
        compared += 1
        mismatch = stored_tier_mismatch(
            driver=driver_id,
            stored=row.tier,
            computed=computed,
            source=f"{LOCK_FILENAME} [[driver]]",
        )
        if mismatch is not None:
            say(mismatch.message)
            failures += 1
            continue
        expected_bits = restriction_bits(card.licence_code)
        if row.restriction_bits != expected_bits:
            say(
                f"{driver_id}: {LOCK_FILENAME} records restriction_bits = "
                f"{row.restriction_bits} and the facts compute {expected_bits}. The bit travels "
                f"to every artefact (INV-16, DR17), so a stale one is a contaminated deliverable"
            )
            failures += 1
    if failures:
        say("")
        say(
            f"ow drivers check EXIT 1  {failures} recorded licence posture(s) disagree with "
            f"compute_tier. The card carries FACTS and the tier is COMPUTED (DR15)"
        )
        return EXIT_FAIL
    # SAY WHICH HALF RAN. The loop above compares a COMPUTED tier against a RECORDED one, so it
    # asserts nothing at all when there is no card to compute from or no lock row to compare
    # against -- and at P3 stage A neither exists: the first first-party cards land at W3.4/W3.5
    # (16-roadmap.md section 6) and `omniweave.lock` is written by `ow drivers add`. Printing
    # "every recorded tier agrees" over an empty loop is an assertion over an empty collection,
    # which passes and proves nothing; the ci.yml step for G28 is the worked example of the
    # alternative -- name the half that ran and the half that did not, so "neither branch can
    # pass for the wrong reason". The exit code stays 0 because nothing DISAGREED, exactly as
    # gate_incremental.py reports "4 check(s) passed, 4 not checked" and still exits 0.
    if not space.cards:
        say(
            "ow drivers check NOT ENFORCED  0 cards, so the computed-vs-recorded comparison "
            "had no subject. The tombstone roster and the lockfile were read; no tier was "
            "checked. The first first-party cards land at W3.4/W3.5 (16-roadmap.md section 6)"
        )
        return EXIT_CLEAN
    if not compared:
        say(
            f"ow drivers check NOT ENFORCED  {len(space.cards)} card(s) read and every tier "
            f"computed, but no {LOCK_FILENAME} [[driver]] row records a tier, so nothing was "
            f"compared. `ow drivers add` is what writes the recorded posture this verb audits"
        )
        return EXIT_CLEAN
    say(
        f"ow drivers check OK  {compared} of {len(space.cards)} card(s) compared against "
        f"{LOCK_FILENAME}; every recorded tier agrees with compute_tier, and so does every "
        f"restriction_bits"
    )
    return EXIT_CLEAN


# --------------------------------------------------------------------------------------------
# 4. verify
# --------------------------------------------------------------------------------------------


def verb_verify(space: Workspace, emit: TextIO) -> int:
    """Recompute `card_sha256` from what is installed and exit non-zero on any drift (:1620).

    `card_sha256` is `sha256:` over the RAW BYTES of `driver.toml` as read from disk
    (04-driver-system.md section 2.8), which is why a comment-only edit moves it: "the lockfile
    and G12 pin *bytes*". `card.py` computes it at load and carries it on the card, so this
    function compares two recorded values and recomputes neither — the recomputation already
    happened, at the one site that reads the file.

    A locked id with no card is drift too, and in the direction that matters: the lock says a
    driver is pinned and the environment does not have it.
    """
    say = _sayer(emit)
    failures = 0
    for driver_id, row in sorted(space.lock.items()):
        card = space.cards.get(driver_id)
        if card is None:
            say(f"{driver_id}: locked at version {row.version!r} and not installed")
            failures += 1
            continue
        if card.card_sha256 != row.card_sha256:
            say(
                f"{driver_id}: card_sha256 drift\n"
                f"  locked     {row.card_sha256}\n"
                f"  installed  {card.card_sha256}\n"
                f"  fix        ow drivers add {row.dist or driver_id}"
            )
            failures += 1
        if row.dist_sha256:
            say(f"{driver_id}: {DIST_DIGEST_UNVERIFIABLE}")
    unlocked = sorted(set(space.cards) - set(space.lock))
    for driver_id in unlocked:
        say(f"{driver_id}: installed and absent from {LOCK_FILENAME} (NOT_IN_LOCKFILE)")
    if failures:
        say("")
        say(f"ow drivers verify EXIT 1  {failures} row(s) drifted from {LOCK_FILENAME}")
        return EXIT_FAIL
    say(f"ow drivers verify OK  {len(space.lock)} locked row(s), no card digest drift")
    return EXIT_CLEAN


# --------------------------------------------------------------------------------------------
# 5. explain
# --------------------------------------------------------------------------------------------


def verb_explain(
    space: Workspace,
    emit: TextIO,
    *,
    requirement: Requirement,
    require_candidate: bool,
    gates: bool,
) -> int:
    """One `resolve()` call, printed. 18-api-sketch.md:2156-2160's shape.

    Each rejection prints its `RejectCode`, the `codes.toml` numeric and symbol that code is a
    typed view of, **the gate that refused** and the detail. The gate is the part worth having:
    which code a driver failing several gates reports is decided by the fixed order of
    04-driver-system.md:1340, and printing the gate name is what turns that order from an
    implementation detail into something an operator can reason about.

    A code with no `codes.toml` row prints `(no OW-D row yet)` rather than a numeric this script
    made up. 01-principles.md:605 makes the missing row a defect class; inventing one here would
    hide it.
    """
    say = _sayer(emit)
    if gates:
        say("the gate order, in the order resolve() walks it (04-driver-system.md:1340-1360):")
        for index, gate in enumerate(GATE_ORDER, start=1):
            codes = " | ".join(code.value for code in gate.codes)
            say(f"  {index:>2}. {gate.name:<34} -> {codes}")
            say(f"      {gate.plan}")
        say("")
    resolution = resolve(requirement, space.catalog, space.policy)
    say(f"resolve({requirement.port}, format={requirement.format or '<any>'})")
    for candidate in resolution.candidates:
        say(
            f"  candidate  {candidate.driver_id:<28} "
            f"isolation={candidate.isolation_granted.value} "
            f"config={candidate.config_digest[:8]}"
        )
    for rejection in resolution.rejected:
        say(
            f"  REJECTED   {rejection.driver_id:<28} {rejection.code.value}  "
            f"({_numeric(rejection.symbol)})"
        )
        say(f"             gate {rejection.gate}")
        for line in rejection.detail.splitlines():
            say(f"             {line}")
    for degradation in resolution.degradations:
        say(f"  degraded   {degradation.driver_id:<28} {degradation.kind}: {degradation.detail}")
    say(f"  resolution_digest {resolution.resolution_digest}")
    say(
        f"  considered {resolution.considered} = {len(resolution.candidates)} candidate(s) "
        f"+ {len(resolution.rejected)} rejection(s)"
    )
    if require_candidate and not resolution.candidates:
        say("")
        say(
            "ow drivers explain EXIT 1  --require-candidate was passed and the resolution is "
            "zero-candidate. A zero-candidate Resolution IS the error message (04:1366) and is "
            "not by itself a failure, which is why this needs a flag"
        )
        return EXIT_FAIL
    _report_json(resolution, say)
    return EXIT_CLEAN


def _numeric(symbol: str) -> str:
    """`OW-D-nnn / SYMBOL` from `codes.toml`, or a named absence."""
    try:
        row = explain(symbol)
    except NotFoundError:
        return f"no OW-D row yet for {symbol}"
    return f"{row.numeric} / {row.symbol}"


def _report_json(resolution: Resolution, say: Callable[[str], None]) -> None:
    """Print the `resolution_report` row's own top-level keys.

    Printed rather than summarised because 04-driver-system.md:1442 makes that row the record of
    what happened, and an operator reading `explain` should be able to see the shape of the row a
    real run would have written.
    """
    say(f"  report_json keys {sorted(resolution_report(resolution))}")


# --------------------------------------------------------------------------------------------
# 6. The command line
# --------------------------------------------------------------------------------------------


def _sayer(out: TextIO) -> Callable[[str], None]:
    """One line to one stream.

    `print` is banned in library code and this is not library code: `tools/gate_semgrep.py:26-37`
    takes that reading for itself, and the module docstring above says why a verb that prints
    cannot live in `omniweave_core`.
    """

    def say(line: str) -> None:
        print(line, file=out)

    return say


def _tiers(raw: str) -> list[str]:
    return [part.strip() for part in raw.split(",") if part.strip()]


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="ow_drivers.py",
        description=(
            "ow drivers check | explain | verify | list, before the CLI exists (ledger D25). "
            "Exit 0 clean, 1 a finding, 2 the verb did not run."
        ),
    )
    parser.add_argument("verb", choices=("list", "check", "verify", "explain"))
    parser.add_argument(
        "--root", type=Path, default=Path(), help="the project root holding omniweave.lock"
    )
    parser.add_argument(
        "--cards",
        type=Path,
        default=None,
        help="read driver.toml files under this directory instead of the installed environment",
    )
    parser.add_argument("--port", default=None, help="list: only this Port, e.g. parse/1")
    parser.add_argument(
        "--posture", action="store_true", help="check: also print section 7.4's posture report"
    )
    parser.add_argument("--format", default="", help="explain: the requirement's media type")
    parser.add_argument("--granularity", default=None, help="explain: document | part | corpus")
    parser.add_argument("--input-kind", default=None, help="explain: an ArtifactKind member")
    parser.add_argument(
        "--requires-produces", default="", help="explain: comma-separated ArtifactKind members"
    )
    parser.add_argument("--pinned", default=None, help="explain: a DriverId, or <id>@<dist>")
    parser.add_argument(
        "--max-cost-class",
        default=CostClass.LOCAL_COMPUTE.value,
        help="explain: free | local_compute | billed_api",
    )
    parser.add_argument(
        "--floor",
        action="append",
        default=[],
        metavar="NAME=VALUE",
        help="explain: a capability floor, repeatable. VALUE true/false, a rung, or a,b set",
    )
    parser.add_argument(
        "--gates", action="store_true", help="explain: print the gate order before resolving"
    )
    parser.add_argument(
        "--require-candidate",
        action="store_true",
        help="explain: exit 1 when the resolution has no candidate",
    )
    parser.add_argument(
        "--enabled", default="", type=_tiers, help="[drivers] enabled, comma-separated"
    )
    parser.add_argument("--allow-tiers", default="open", type=_tiers, help="[licence] allow_tiers")
    parser.add_argument(
        "--allow-cost-classes",
        default="free,local_compute",
        type=_tiers,
        help="[drivers.cost] allow_classes",
    )
    parser.add_argument("--jurisdiction", default="", help="[licence] jurisdiction")
    parser.add_argument("--fields-of-use", default="", type=_tiers, help="[licence] fields_of_use")
    parser.add_argument(
        "--no-require-lock",
        dest="require_lock",
        action="store_false",
        help="[drivers] require_lock = false (the shipped default is true)",
    )
    parser.add_argument(
        "--allow-unattested",
        action="store_true",
        help="[drivers] allow_unattested = true (the shipped default is false)",
    )
    return parser


def _requirement(args: argparse.Namespace) -> Requirement:
    floors: dict[str, object] = {}
    for clause in args.floor:
        name, _, value = clause.partition("=")
        floors[name.strip()] = _floor_value(value.strip())
    return Requirement(
        port=args.port or "parse/1",
        format=args.format,
        floors=floors,  # type: ignore[arg-type]
        max_cost_class=CostClass(args.max_cost_class),
        granularity=args.granularity,
        input_kind=ArtifactKind(args.input_kind) if args.input_kind else None,
        requires_produces=frozenset(ArtifactKind(name) for name in _tiers(args.requires_produces)),
        pinned=args.pinned,
    )


def _floor_value(raw: str) -> object:
    if raw in ("true", "false"):
        return raw == "true"
    if "," in raw:
        return frozenset(part.strip() for part in raw.split(",") if part.strip())
    return raw


def main(argv: Sequence[str] | None = None, *, out: TextIO | None = None) -> int:
    """Read the tree, run one verb, return its exit code."""
    stream = sys.stdout if out is None else out
    say = _sayer(stream)
    args = _parser().parse_args(None if argv is None else list(argv))
    try:
        space = workspace(args)
        requirement = _requirement(args) if args.verb == "explain" else None
    except (
        OSError,
        ValueError,
        KeyError,
        tomllib.TOMLDecodeError,
        DriverHostError,
        ImportError,
    ) as exc:
        say(f"ow drivers {args.verb} DID NOT RUN  {type(exc).__name__}: {exc}")
        return EXIT_NOT_RUN

    if args.verb == "list":
        return verb_list(space, stream, port=args.port)
    if args.verb == "check":
        return verb_check(space, stream, posture=args.posture)
    if args.verb == "verify":
        return verb_verify(space, stream)
    if requirement is None:  # pragma: no cover - argparse's choices make this unreachable
        say(f"ow drivers {args.verb} DID NOT RUN  no requirement was built")
        return EXIT_NOT_RUN
    return verb_explain(
        space,
        stream,
        requirement=requirement,
        require_candidate=args.require_candidate,
        gates=args.gates,
    )


if __name__ == "__main__":
    raise SystemExit(main())
