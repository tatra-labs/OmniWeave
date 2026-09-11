"""Suite 1 of 12 -- `card`: the descriptor parses, and says only things it is entitled to say.

04-driver-system.md:2070, the row in full: "the card parses; every required key is present and in
domain; `attestation` is top-level; `[limits]` <= `HOST_MAX`; every section-4.5 cap holds; every
benchmark row has `n >= 30`, `ci95`, `witness` and a complete ten-field `measured_on`". The defect
it catches: "a card with seven `MeasuredOn` fields and a blank cell".

## Most of that row is already a refusal, so most of this suite would be a test that cannot fail

`load_card()` enforces the domain checks, the `[limits]` ceiling, the section-4.5 caps and the
benchmark shape -- `MeasuredOn` is frozen with no defaults, so a card supplying seven of its ten
fields raises `TypeError` at construction (13-quality.md:1759) and never becomes a `DriverCard` at
all. A suite that re-ran the loader and asserted "it loaded" would be asserting that the object it
was handed exists.

So this suite is written around **the four things the loader deliberately does not refuse**, and
those are where its assertions can fail:

1. **`attested`.** 04-driver-system.md:2098-2101: a recomputed `attestation` that does not match
   "sets `card.attested = False`, and an unattested driver is never auto-selected" -- and card.py's
   own docstring is explicit that this is "**not** a rejection: attestation is tamper-evidence, not
   authentication". The loader carries the bit; something has to *read* it, and this is that thing.
2. **`degradations`.** An unknown key inside `[capability.<port>]` is IGNORED with a recorded
   `CARD_CAPABILITY_UNKNOWN`, because every key there is a floor and an unrecognised one can only
   make the driver look LESS capable (04 section 2.1). The card loads; the key does nothing; the
   author believes they declared something. 04:2314's console line "0 unknown [capability.parse]"
   is this count.
3. **The bytes on disk right now.** `Subject.of()` loaded the card once. `ow conform --bench`
   writes `[quality]` and `[cost.measured]` back into the same file, and 04:2386-2389 records what
   an unre-read card costs: "the next `ow conform` would validate the card the cache remembered
   rather than the one just edited, and the whole loop above would be a lie exactly once,
   silently". This suite re-reads from disk and compares digests.
4. **The headroom.** Every cap the loader enforces as a refusal is reported here as a distance --
   "card 3.9 KB of 64 KB" (04:2314) -- because a card at 63 KB passes and is one benchmark row
   away from failing, and a pass/fail verdict cannot say that.

Specified in 04-driver-system.md section 8.2 row 1, section 2.8 and section 4.5.
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING, Final

from omniweave_core.canonical import JsonValue
from omniweave_core.drivers.card import (
    MEASURED_ON_FIELDS,
    MIN_SLICE_N,
    WITNESSES,
    attestation_of,
    card_sha256,
    read_card_bytes,
)
from omniweave_core.limits import (
    MAX_CARD_BENCHMARKS,
    MAX_CARD_BINARIES,
    MAX_CARD_BYTES,
    MAX_CARD_CONFIG_PROPERTIES,
    MAX_CARD_FORMATS,
    MAX_CARD_PINS,
    MAX_ENTRY_BYTES,
    MAX_ENTRY_COUNT,
)

from omniweave_conform.result import Assertion, SuiteResult

if TYPE_CHECKING:
    from collections.abc import Iterator

    from omniweave_conform.subject import Subject

SUITE = "card"

_NS_PER_MS: Final = 1_000_000
"""Nanoseconds per millisecond.

`time.monotonic_ns()` rather than `time.perf_counter()` because
`tools/semgrep/omniweave.yaml`'s `omniweave-no-time-time-in-library-code` bans the latter
across `packages/*/src/**` and the rule's own message names this as the replacement: the
clock is injected, "`time.monotonic_ns()` for a duration". Every reading in this module is a
duration."""

_KIB = 1024
_ATTESTATION_KEY = "attestation"


def run(subject: Subject) -> SuiteResult:
    """The `card` suite. Imports no driver code and opens no fixture."""
    started = time.monotonic_ns()
    checks = list(_assertions(subject))
    caps = sum(1 for a in checks if a.locus.startswith("cap:"))
    size = len(subject.raw)
    summary = (
        f"{_key_count(subject)} keys, {len(subject.card.degradations)} unknown "
        f"[capability.*], attestation {_attestation_state(subject)}, "
        f"card {size / _KIB:.1f} KB of {MAX_CARD_BYTES // _KIB} KB, {caps} caps checked"
    )
    return SuiteResult.of(
        SUITE,
        checks,
        summary=summary,
        elapsed_ms=(time.monotonic_ns() - started) / _NS_PER_MS,
    )


def _attestation_state(subject: Subject) -> str:
    if subject.card.attestation is None:
        return "absent"
    return "ok" if subject.card.attested else "MISMATCH"


def _key_count(subject: Subject) -> int:
    """Top-level keys plus every key inside every table, one level of nesting deep.

    04:2314 prints "43 keys" for the ipynb card. The number is a *report*, so what matters is that
    it is derived from the card rather than from a constant -- a hand-written count would be a
    number that stops being true the first time a key is added.
    """
    import tomllib  # noqa: PLC0415 -- the raw document, not the validated card.

    document = tomllib.loads(subject.raw.decode("utf-8"))
    return _count_keys(document)


def _count_keys(value: object) -> int:
    if not isinstance(value, dict):
        return 0
    return len(value) + sum(_count_keys(child) for child in value.values())


def _assertions(subject: Subject) -> Iterator[Assertion]:
    yield from _attestation_assertions(subject)
    yield from _degradation_assertions(subject)
    yield from _freshness_assertions(subject)
    yield from _cap_assertions(subject)
    yield from _benchmark_assertions(subject)


def _attestation_assertions(subject: Subject) -> Iterator[Assertion]:
    """`attestation` present, top-level, and recomputing to what the card says.

    A card with NO `attestation` is not a failure of this suite. 04-driver-system.md:2160 has
    `ow drivers scaffold` emit one with "`[cost.measured]`, `[quality]` and `attestation` absent",
    and 04:2331 has `ow conform` write it at the end of a passing run -- so an absent attestation
    is the state of every card that has not yet had a conformance run, which is every card the
    first time this suite sees it. Refusing it would make the kit unable to certify anything.
    A *wrong* one is a failure, and that is a different claim.
    """
    card = subject.card
    if card.attestation is None:
        yield Assertion(
            "attestation is absent, which is the pre-run state a scaffold emits",
            ok=True,
            detail="ow conform writes it at the end of a passing run (04:2331)",
            locus="attestation",
        )
        return
    yield Assertion(
        "attestation is a top-level key",
        ok=_attestation_is_top_level(subject.raw),
        detail=(
            "TOML scopes a bare key to the most recent header, so an attestation line written "
            "after a table header parses as that table's key and the recomputation reads nothing"
        ),
        locus="attestation",
    )
    recomputed = _recompute(subject)
    yield Assertion(
        "the recomputed attestation matches the declared one",
        ok=card.attested,
        detail="a mismatch is tamper-evidence, never authentication (04:2098-2101)",
        locus="attestation",
        expected=card.attestation,
        actual=recomputed,
    )


def _attestation_is_top_level(raw: bytes) -> bool:
    """True when `attestation = ` appears before the first `[` table header.

    Read off the raw bytes rather than off the parsed document, because the parsed document cannot
    tell you where the key *was*: a correctly placed `attestation` and one absorbed as
    `quality.suites.attestation` are two different documents, and only one of them has a top-level
    key -- which the loader already checks. The value of doing it again over bytes is that this
    assertion names the line, which a loader refusal does not.
    """
    for line in raw.decode("utf-8", errors="replace").splitlines():
        stripped = line.strip()
        if stripped.startswith("["):
            return False
        if stripped.startswith(_ATTESTATION_KEY) and "=" in stripped:
            return True
    return False


def _recompute(subject: Subject) -> str:
    import tomllib  # noqa: PLC0415 -- the canonical form is over the raw document.

    document: dict[str, JsonValue] = tomllib.loads(subject.raw.decode("utf-8"))
    return attestation_of(document)


def _degradation_assertions(subject: Subject) -> Iterator[Assertion]:
    """Zero recorded `CARD_CAPABILITY_UNKNOWN` degradations.

    Each one is a key the author wrote and the loader ignored. The card is valid; the intent is
    not. This is the one place in the whole pipeline where that difference is reported, because
    `resolve()` reads the parsed floors and never looks at what was dropped on the way in.
    """
    degradations = subject.card.degradations
    yield Assertion(
        "no [capability.*] key was ignored as unknown",
        ok=not degradations,
        detail=(
            "; ".join(f"{d.table}.{d.key}: {d.detail}" for d in degradations)
            if degradations
            else "every declared capability key is one the grammar knows"
        ),
        locus="cap:degradations",
    )


def _freshness_assertions(subject: Subject) -> Iterator[Assertion]:
    """The bytes on disk are still the bytes this run validated.

    04:2386-2389's editable-install lesson, generalised: a card that changed under the run is a run
    whose report describes a file that no longer exists.
    """
    try:
        current = read_card_bytes(subject.card_path)
    except OSError as exc:
        yield Assertion(
            "the card is still readable at the path the run was pointed at",
            ok=False,
            detail=f"{type(exc).__name__}: {exc}",
            fixture=subject.card_path.name,
            locus="freshness",
        )
        return
    yield Assertion(
        "the card on disk is byte-identical to the one this run validated",
        ok=current == subject.raw,
        detail="a card edited mid-run makes the report describe a file that no longer exists",
        fixture=subject.card_path.name,
        locus="freshness",
        expected=card_sha256(subject.raw),
        actual=card_sha256(current),
    )


def _cap_assertions(subject: Subject) -> Iterator[Assertion]:
    """Every section-4.5 cap, as a distance rather than as a verdict.

    The loader refuses a breach, so each of these can only fail if a cap was raised in
    `omniweave_core.limits` without the loader being taught about it -- which is a real failure
    mode and exactly the one INV-22 exists to bound ("limits are host constants, clampable down
    only"). Reported with both numbers so a card near a ceiling is visible before it crosses one.
    """
    card = subject.card
    rows = (
        ("card bytes", len(subject.raw), MAX_CARD_BYTES),
        ("[capability] formats", len(card.capability.formats), MAX_CARD_FORMATS),
        ("[hardware] needs_binaries", len(card.hardware.needs_binaries), MAX_CARD_BINARIES),
        ("[deps] pins", len(card.deps.pins), MAX_CARD_PINS),
        ("[[quality.benchmark]]", len(card.quality.benchmarks), MAX_CARD_BENCHMARKS),
        (
            "[config] properties",
            len(card.config.properties),
            MAX_CARD_CONFIG_PROPERTIES,
        ),
        ("[limits] max_input_bytes", card.limits.max_input_bytes, MAX_ENTRY_BYTES),
        ("[limits] max_parts", card.limits.max_parts, MAX_ENTRY_COUNT),
    )
    for name, value, ceiling in rows:
        yield Assertion(
            f"{name} is within its host ceiling",
            ok=value <= ceiling,
            detail=f"{value} of {ceiling}",
            locus=f"cap:{name}",
            expected=f"<= {ceiling}",
            actual=str(value),
        )


def _benchmark_assertions(subject: Subject) -> Iterator[Assertion]:
    """`n >= 30`, a `ci95`, a known `witness`, and ten `measured_on` fields, per row.

    `Benchmark.__post_init__` and `MeasuredOn`'s frozen ten already refuse most of this at load,
    which is why the row 04:2070 describes as the defect -- "a card with seven `MeasuredOn` fields
    and a blank cell" -- cannot reach a `DriverCard`. What is checked here and nowhere else is the
    `corpus_digest`: DR24 rewrites a witness at card load for a digest outside the release
    manifest, and this suite reports a row carrying an EMPTY one, which no loader refuses because
    an empty string is a string.
    """
    benchmarks = subject.card.quality.benchmarks
    if not benchmarks:
        yield Assertion(
            "no [[quality.benchmark]] row to check",
            ok=True,
            detail="a driver that declines to produce a number is honest rather than deficient",
            locus="benchmark",
        )
        return
    for index, row in enumerate(benchmarks):
        where = f"benchmark[{index}] {row.metric}"
        yield Assertion(
            "n is at least the minimum slice",
            ok=row.n >= MIN_SLICE_N,
            detail=f"n={row.n}",
            locus=where,
            expected=f">= {MIN_SLICE_N}",
            actual=str(row.n),
        )
        yield Assertion(
            "ci95 is an interval containing the point estimate",
            ok=row.ci95[0] <= row.value <= row.ci95[1],
            detail=f"{row.value} in {row.ci95}",
            locus=where,
        )
        yield Assertion(
            "witness is one of the three",
            ok=row.witness in WITNESSES,
            detail="a witness the loader does not recognise is downgraded to self (04:2130)",
            locus=where,
            expected="/".join(WITNESSES),
            actual=row.witness,
        )
        blank = [
            name
            for name in MEASURED_ON_FIELDS
            if not str(getattr(row.measured_on, name, "")).strip()
        ]
        yield Assertion(
            "every measured_on field carries a value",
            ok=not blank,
            detail=(
                f"blank: {', '.join(blank)}"
                if blank
                else f"all {len(MEASURED_ON_FIELDS)} fields populated"
            ),
            locus=where,
        )
