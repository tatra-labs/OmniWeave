"""The badge string, and it is GENERATED so that it cannot be written by hand.

04-driver-system.md:2394-2395 prints it:

    $ ow conform --badge
    omniweave-conform 1.0.0 · mandatory 11/11 pass · quality unknown · card sha256:8367cd66...

:2115 says what it must encode -- "`kit_version`, the twelve suite results and `card_sha256`" --
and :2398 says what it is: "That string, and the sentence 'passes the omniweave conformance kit
1.0.0, mandatory suites', are the whole of the claim."

## Why a generator and not a template in the README

04-driver-system.md:2119-2121's entitlement table gives the mechanism for refusing "certified",
"verified by omniweave" and "official": "trademark policy, plus **the badge string being
generated**". A badge an author types is a badge an author can improve. So the two entitled strings
have exactly one producer each, they are computed from a `ConformReport`, and every field in them
comes off that report rather than off an argument.

`SENTENCE` is the second entitled string and it is deliberately parameterised on `kit_version`
alone: it says "mandatory suites" and nothing about *how many*, because the count belongs in the
badge where `card_sha256` can be checked beside it.

## What the badge does NOT say

No quality ranking, no accuracy number, no word that implies review. `quality unknown` is printed
as the honest state it is -- 13-quality.md:1747 makes declining to produce a number "honest rather
than deficient", and a badge that omitted the field would let a reader assume the driver had one.

Specified in 04-driver-system.md section 8.4.
"""

from __future__ import annotations

from importlib import metadata
from typing import TYPE_CHECKING, Final

from omniweave_conform.result import Verdict

if TYPE_CHECKING:
    from omniweave_conform.result import ConformReport

__all__ = ["DISTRIBUTION", "SENTENCE", "badge", "kit_version", "sentence"]

DISTRIBUTION: Final = "omniweave-conform"
SEPARATOR: Final = " · "
"""U+00B7 MIDDLE DOT with a space each side, as 04-driver-system.md:2395 prints it. Spelled as an
escape rather than as a literal so that a reader of this file knows which of the several dot
characters it is, and so no editor's normalisation can quietly change the emitted bytes."""

SENTENCE: Final = "passes the omniweave conformance kit {version}, mandatory suites"
"""04-driver-system.md:2116 and :2398, verbatim. The second of the two entitled strings."""

_DIGEST_SHOWN: Final = 8
"""How many hex characters of `card_sha256` the badge shows. Eight, as :2395 prints
(`sha256:8367cd66...`): enough to match against a published card by eye, and far short of a
claim that the truncation is collision-resistant."""


def kit_version() -> str:
    """The installed `omniweave-conform` version, or `0+unknown` when it is not installed.

    Read from distribution metadata rather than from a constant in this file, because a version
    written twice is a version that can disagree with itself -- and this one ends up inside a
    string an author publishes. `0+unknown` is a PEP 440 local version: it sorts below every real
    release and it is visibly not one, so a badge carrying it cannot be mistaken for a tagged run.
    """
    try:
        return metadata.version(DISTRIBUTION)
    except metadata.PackageNotFoundError:
        return "0+unknown"


def badge(report: ConformReport) -> str:
    """The exact string `ow conform --badge` emits.

    Every field comes off the report: the kit version it was produced by, the mandatory tally with
    its denominator, `quality`'s own verdict, and the card digest the run validated.
    """
    quality = report.verdict_of("quality")
    tier = "pass" if report.passed else "FAIL"
    return SEPARATOR.join(
        (
            f"{DISTRIBUTION} {report.kit_version}",
            f"mandatory {report.mandatory_passed}/{report.mandatory_total} {tier}",
            f"quality {quality.value}",
            f"card {_short(report.card_sha256)}",
        )
    )


def sentence(report: ConformReport) -> str:
    """The second entitled string, or an empty one for a run that did not earn it.

    An empty string rather than a hedged sentence: there is no honest variant of "passes the
    omniweave conformance kit" for a run that did not, and offering a softer form would be offering
    the marketing surface 04:2134 says a conformance kit must not become.
    """
    if not report.passed:
        return ""
    return SENTENCE.format(version=report.kit_version)


def _short(digest: str) -> str:
    """`sha256:8367cd66...` from `sha256:8367cd66...64 hex...`, prefix preserved."""
    prefix, _, body = digest.partition(":")
    if not body:
        return f"sha256:{digest[:_DIGEST_SHOWN]}..."
    return f"{prefix}:{body[:_DIGEST_SHOWN]}..."


def suite_table(report: ConformReport) -> dict[str, str]:
    """`{suite: verdict}` for the twelve, for `[quality.suites]`.

    Every suite in `SUITES` appears, including any that did not report: an absent suite writes
    `unknown`, which is the value the card grammar has for "we do not know" and is the only honest
    thing to record for a suite that never ran.
    """
    by_suite = report.by_suite()
    from omniweave_conform.result import SUITES  # noqa: PLC0415 -- avoids a module-level cycle.

    return {
        name: (by_suite[name].verdict if name in by_suite else Verdict.UNKNOWN).value
        for name in SUITES
    }
