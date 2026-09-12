"""Suite 4 of 12 -- `capability`: the card is checked against the code in BOTH directions.

04-driver-system.md:2681 names this file for DR12: "assertions **derived** from the card, both
directions". :2077 is the row: "`text_span = false` asserts text spans are *absent*;
`origin_span = "exact"` re-reads the retained part on the branch the driver's `os_kind` selects".
The defect it catches: **an aspirational card**.

This is the suite 16-roadmap.md:486 singles out -- "`capability` alone must prove `origin_span` on
all three INV-10 branches, which is why the mandatory tier is eleven suites and still has to run in
five minutes on a laptop" -- and 03-document-model.md:3030 calls P7 "the only mechanism that makes a
third party's honesty machine-checkable".

## The properties, and where each number comes from

03-document-model.md section 15's property table assigns each `P`-number to a suite. The ones
assigned to `capability` and observable in `owdoc-fragment/1` are implemented here under their own
numbers, so a reader can go from an assertion name back to one row of that table:

| P | claim |
|---|---|
| P6 | every `quad` lies inside the page frame with `QUAD_SLACK_MPT` of slack; none is zero |
| P7 | `origin_span = "exact"`: re-read the retained part on the branch `os_kind` selects |
| P8 | `ts_a`/`ts_b` non-NULL implies `0 <= ts_a <= ts_b <= len(text)` |
| P9 | every mark satisfies `0 <= a <= b <= len(text)`; a `link` mark has a non-empty `target` |
| P14 | honesty over ABSENCE: `text_span = false` asserts spans absent, `math = {}` asserts no |
| | formula block carries a notation, `assets = "none"` asserts zero asset drafts |
| P15 | `achieved <= declared`, field by field: ordered keys with `>=`, `math` with superset, |
| | booleans with implication |
| P16 | `os_*` matches one row of section 7.2's mapping; `os_kind = pixels` implies a quad |
| P32 | `origin_span = "normalized"`: an address that LOCATES and does not prove |

Plus the sixteenth key's obligation, which 04-driver-system.md:512 states as a conformance failure
in as many words: every `[capability.parse] format_tokens` pair "must appear in the driver's
`sniff()` output as a `FormatGuess` whose `media_type` and `format_token` are that pair, or the
`capability` suite fails".

## Why P15 reuses `meets_floor` instead of comparing ladders itself

`omniweave_core.drivers.resolve.meets_floor(port, name, declared, floor)` is the one home for
"does this value meet that one" across ordered ladders, boolean floors, set floors and the single
inverted key (`forfeits`, compared subset -- 04:2494, "the only inverted comparison on the whole
card"). P15 is the same question with the arguments swapped: `achieved` is the floor and the card's
declaration is what must meet it. Re-deriving the comparison here would put the `forfeits` inversion
in two places, and the failure mode of that is a kit which reads an over-claim as an under-claim on
exactly the key where the direction is reversed.

## What P7's failure message must contain

04-driver-system.md:2334: "the message names the fixture, the block and the two strings that
differed -- because the point of a capability suite is to be *actionable*, not to be a verdict."
Every P7 assertion carries `fixture`, the block's `tmp` id as `locus`, and both strings.

Specified in 04-driver-system.md section 8.2 row 4 and section 2.2; 03-document-model.md section 15;
DR12.
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING, Any, Final

from omniweave_core.drivers.card import PARSE_BOOLS, PARSE_LADDERS, PARSE_SETS
from omniweave_core.drivers.resolve import meets_floor
from omniweave_core.errors import DriverHostError
from omniweave_core.limits import MAX_MARKS_PER_BLOCK
from omniweave_ports.detect import StreamHint
from omniweave_ports.types import DriverError, Port

from omniweave_conform.harness import ORIGIN_VERIFIER, nfc, reverify_origin, run_parse
from omniweave_conform.result import Assertion, SuiteResult

if TYPE_CHECKING:
    from collections.abc import Iterator, Mapping, Sequence

    from omniweave_conform.harness import ParseRun
    from omniweave_conform.subject import Subject

SUITE = "capability"

_NS_PER_MS: Final = 1_000_000
"""Nanoseconds per millisecond.

`time.monotonic_ns()` rather than `time.perf_counter()` because
`tools/semgrep/omniweave.yaml`'s `omniweave-no-time-time-in-library-code` bans the latter
across `packages/*/src/**` and the rule's own message names this as the replacement: the
clock is injected, "`time.monotonic_ns()` for a duration". Every reading in this module is a
duration."""

QUAD_SLACK_MPT: Final = 3000
"""P6's tolerance, in millipoints: 3 pt.

03-document-model.md:2990 states it and gives the reason -- "enough for a real bleed or a skewed
scan line and far short of a frame error". It lives here rather than in `omniweave_core.limits`
because this suite is its only consumer today and `limits.__all__` is a register
`test_limits.py:122` compares against the plan's own list; the moment a second consumer appears it
belongs there instead, and this comment is the note to move it."""

_QUAD_CORNERS: Final = 4
_SNIFF_HEAD_BYTES: Final = 8192

_FIFTEEN: Final[tuple[str, ...]] = (
    *PARSE_LADDERS.keys(),
    *PARSE_BOOLS,
    *PARSE_SETS.keys(),
)
"""The fifteen, assembled from the grammar's own three groups rather than written out.

Ten ordered ladders plus three booleans plus two sets is fifteen, and the assembly is the check:
if a key moved between groups, or a sixteenth appeared, this tuple changes with it and
`test_conform_capability.py`'s length assertion is what notices."""


def run(subject: Subject) -> SuiteResult:
    """The `capability` suite."""
    started = time.monotonic_ns()
    elapsed = lambda: (time.monotonic_ns() - started) / _NS_PER_MS  # noqa: E731

    if subject.card.identity.port is not Port.PARSE:
        return SuiteResult.of(
            SUITE,
            [],
            unknown=(
                f"this kit's capability assertions are written over owdoc-fragment/1, which is "
                f"a parse/1 artifact; {subject.card.identity.port.value}/1 needs its own"
            ),
            elapsed_ms=elapsed(),
        )
    if subject.card.parse is None:
        return SuiteResult.of(
            SUITE,
            [
                Assertion(
                    "a parse/1 card declares [capability.parse]",
                    ok=False,
                    detail="there is nothing to check the code against",
                    locus="card",
                )
            ],
            elapsed_ms=elapsed(),
        )
    if not subject.fixtures:
        return SuiteResult.of(
            SUITE,
            [],
            unknown=(
                "--fixtures named no readable file; every assertion in this suite is over a "
                "parsed document, and a suite with no subject must not read as a pass"
            ),
            elapsed_ms=elapsed(),
        )

    try:
        driver = subject.instantiate()
    except (DriverHostError, DriverError, TypeError, ValueError) as exc:
        return SuiteResult.of(
            SUITE,
            [
                Assertion(
                    "the driver constructs, so its capabilities can be checked",
                    ok=False,
                    detail=f"{type(exc).__name__}: {exc}",
                    locus="construct",
                )
            ],
            elapsed_ms=elapsed(),
        )

    runs, checks = _parse_all(subject, driver)
    checks.extend(_format_token_assertions(subject, driver))
    for run_result in runs:
        checks.extend(_per_document(subject, run_result, driver))
    checks.extend(_achieved_assertions(subject, runs))

    blocks = sum(len(r.blocks) for r in runs)
    proved = sum(1 for a in checks if a.locus.startswith("P7:") and a.ok)
    summary = (
        f"{len(_FIFTEEN)} declared, {len(_FIFTEEN)} asserted present-or-absent; "
        f"origin_span={subject.card.parse.origin_span} checked on {proved} of {blocks} blocks "
        f"across {len(runs)} fixtures"
    )
    return SuiteResult.of(SUITE, checks, summary=summary, elapsed_ms=elapsed())


def _parse_all(subject: Subject, driver: object) -> tuple[list[ParseRun], list[Assertion]]:
    """Parse every fixture once. A fixture the driver refuses is not a capability failure.

    `DriverError` here means the driver declined this input, which `contract` already classified
    and which says nothing about whether the card is honest. Silently dropping it would hide a
    driver that refuses everything, so the count of refusals is reported as an assertion.
    """
    runs: list[ParseRun] = []
    refused: list[str] = []
    scratch = subject.scratch(SUITE)
    for index, fixture in enumerate(subject.fixtures):
        try:
            runs.append(run_parse(driver, fixture, scratch / f"f{index}"))
        except DriverError:
            refused.append(fixture.name)
        except Exception as exc:  # attributed by `contract`; counted here.
            refused.append(f"{fixture.name} ({type(exc).__name__})")
    checks = [
        Assertion(
            "at least one fixture parsed, so the card has something to be checked against",
            ok=bool(runs),
            detail=f"{len(runs)} parsed, {len(refused)} refused: {', '.join(refused[:4])}",
            locus="corpus",
        )
    ]
    return runs, checks


def _format_token_assertions(subject: Subject, driver: object) -> Iterator[Assertion]:
    """04-driver-system.md:512: every declared pair must appear in `sniff()`'s output.

    Run over each fixture's own head, because `sniff` is allowed to rank by filename and a driver
    whose pair only surfaces for a `.txt` name is still honest about the pair. A pair that no
    fixture elicits is a failure naming the pair, which is the actionable form.
    """
    parse = subject.card.parse
    if parse is None or not parse.format_tokens:
        return
    seen: set[tuple[str, str]] = set()
    sniff = getattr(driver, "sniff", None)
    if sniff is None:
        yield Assertion(
            "format_tokens are declared and sniff() exists to produce them",
            ok=False,
            detail="the card declares format_tokens and the driver has no sniff()",
            locus="format_tokens",
        )
        return
    for fixture in subject.fixtures:
        hint = StreamHint(
            filename=fixture.name,
            extension=fixture.path.suffix or None,
            declared_media_type=None,
            byte_len=fixture.byte_len,
        )
        try:
            guesses = sniff(fixture.data[:_SNIFF_HEAD_BYTES], hint)
        except Exception:  # noqa: S112 -- a sniff that raises leaves the pair unseen, which the
            continue  # per-pair assertion below reports by name. Nothing is swallowed.
        seen.update((g.media_type, g.format_token) for g in guesses)
    for pair in parse.format_tokens:
        wanted = (pair.media_type, pair.token)
        yield Assertion(
            "every declared format_tokens pair appears in sniff()'s output",
            ok=wanted in seen,
            detail=(
                "04:512 -- a pair no sniff() produces is a token nothing can route to"
                if wanted not in seen
                else f"{pair.media_type} -> {pair.token}"
            ),
            locus=f"format_tokens:{pair.token}",
            expected=f"{pair.media_type} -> {pair.token}",
            actual="; ".join(f"{m} -> {t}" for m, t in sorted(seen)) or "sniff() produced nothing",
        )


def _per_document(subject: Subject, run_result: ParseRun, driver: object) -> Iterator[Assertion]:
    parse = subject.card.parse
    assert parse is not None
    yield from _origin_span_assertions(parse.origin_span, run_result, driver)
    yield from _origin_column_assertions(run_result)
    yield from _text_span_assertions(subject, run_result)
    yield from _mark_assertions(subject, run_result)
    yield from _quad_assertions(subject, run_result)
    yield from _absence_assertions(subject, run_result)


def _origin_span_assertions(
    declared: str, run_result: ParseRun, driver: object
) -> Iterator[Assertion]:
    """P7 for `exact`, P32 for `normalized`, and the absence check for `none`."""
    name = run_result.fixture.name
    if declared == "none":
        offenders = [b for b in run_result.blocks if _os_kind(b) not in {"", "none"}]
        yield Assertion(
            "origin_span = none, and no block carries an address",
            ok=not offenders,
            detail=f"{len(offenders)} blocks carry an os record",
            fixture=name,
            locus="P14:origin_span",
        )
        return
    body = [b for b in run_result.blocks if b.get("layer", "body") == "body"]
    if declared == "normalized":
        unaddressed = [b for b in body if _os_kind(b) in {"", "none"} or not _os_part(b)]
        yield Assertion(
            "origin_span = normalized, and every body block locates",
            ok=not unaddressed,
            detail=(
                "P32: an address that LOCATES and does not prove. A driver declaring normalized "
                "and emitting no address fails, because retain_parts reads the DECLARATION"
            ),
            fixture=name,
            locus="P32:origin_span",
            expected=f"{len(body)} body blocks addressed",
            actual=f"{len(body) - len(unaddressed)} addressed",
        )
        return
    hook = getattr(driver, ORIGIN_VERIFIER, None)
    for block in body:
        yield _reverify(run_result, block, hook)


def _reverify(run_result: ParseRun, block: Mapping[str, Any], hook: object = None) -> Assertion:
    """P7: re-read the retained part on the branch `os_kind` selects and assert equality.

    The three-branch decision itself is `harness.reverify_origin()` and is not repeated here.
    `evaluate.span_exact_rate` asks the identical question of a different population — blocks whose
    own `quote` claims `verbatim`, rather than every body block of a card declaring
    `origin_span = "exact"` — and two copies of INV-10's re-read that could drift apart is the
    thing INV-21 is about. What stays here is the part that is genuinely this suite's: turning the
    verdict into an `Assertion` with P7's own claim wording and locus.
    """
    tmp = str(block.get("tmp", "?"))
    text = str(block.get("text", ""))
    origin = block.get("os") or {}
    check = reverify_origin(run_result.fixture.data, origin, text, hook)
    name = run_result.fixture.name
    if check.branch == "bytes":
        claim = "origin_span = exact re-reads the retained part and matches"
        expected = nfc(text)
    elif check.branch in {"nodepath", "glyphs"}:
        claim = (
            f"origin_span = exact re-verifies on the {check.branch} branch"
            if hook is not None
            else f"origin_span = exact on the {check.branch} branch is re-verified"
        )
        expected = text
    else:
        claim = "origin_span = exact, and every body block carries a re-verifiable address"
        expected = "bytes / nodepath / glyphs"
    return Assertion(
        claim,
        ok=check.ok,
        detail=check.detail,
        fixture=name,
        locus=f"P7:{tmp}",
        expected=expected[:120],
        actual=check.got[:120],
    )


def _origin_column_assertions(run_result: ParseRun) -> Iterator[Assertion]:
    """P16: the `os_*` columns match exactly one row of section 7.2's mapping.

    Two clauses are checkable from the fragment and both are checked: `os_kind = pixels` implies a
    quad, and `os_b` (the LENGTH) is never negative. The third -- "is never used as an end offset"
    -- is not observable from one record, because a length and an end offset are both integers; it
    is observable from the re-read, which is P7, and a driver that used an end offset fails there.
    """
    bad_pixels: list[str] = []
    negative: list[str] = []
    for block in run_result.blocks:
        origin = block.get("os") or {}
        kind = str(origin.get("k", "none"))
        if kind == "pixels" and block.get("quad") is None:
            bad_pixels.append(str(block.get("tmp", "?")))
        length = origin.get("length")
        if isinstance(length, int) and length < 0:
            negative.append(str(block.get("tmp", "?")))
    name = run_result.fixture.name
    yield Assertion(
        "os_kind = pixels implies a non-null quad",
        ok=not bad_pixels,
        detail=f"blocks without a quad: {', '.join(bad_pixels[:5])}" if bad_pixels else "none",
        fixture=name,
        locus="P16:pixels",
    )
    yield Assertion(
        "os length is never negative",
        ok=not negative,
        detail=f"blocks: {', '.join(negative[:5])}" if negative else "none",
        fixture=name,
        locus="P16:length",
    )


def _text_span_assertions(subject: Subject, run_result: ParseRun) -> Iterator[Assertion]:
    """P8 when spans exist, P14's absence clause when the card says they do not."""
    parse = subject.card.parse
    assert parse is not None
    name = run_result.fixture.name
    spanned = [b for b in run_result.blocks if b.get("ts") is not None]
    if not parse.text_span:
        yield Assertion(
            "text_span = false, and no block carries a text span",
            ok=not spanned,
            detail=f"{len(spanned)} blocks carry a ts record",
            fixture=name,
            locus="P14:text_span",
        )
        return
    bad: list[str] = []
    for block in spanned:
        span = block.get("ts") or {}
        start, end = span.get("a"), span.get("b")
        text = str(block.get("text", ""))
        ints = isinstance(start, int) and isinstance(end, int)
        if not ints or not 0 <= start <= end <= len(text):
            bad.append(str(block.get("tmp", "?")))
    yield Assertion(
        "every text span satisfies 0 <= ts_a <= ts_b <= len(text)",
        ok=not bad,
        detail=f"out of range: {', '.join(bad[:5])}" if bad else f"{len(spanned)} spans in range",
        fixture=name,
        locus="P8:text_span",
    )


def _mark_assertions(subject: Subject, run_result: ParseRun) -> Iterator[Assertion]:
    """P9 when marks exist, P14's absence clause when `marks = false`."""
    parse = subject.card.parse
    assert parse is not None
    name = run_result.fixture.name
    marked = [b for b in run_result.blocks if b.get("marks")]
    if not parse.marks:
        yield Assertion(
            "marks = false, and no block carries a mark",
            ok=not marked,
            detail=f"{len(marked)} blocks carry marks",
            fixture=name,
            locus="P14:marks",
        )
        return
    out_of_range: list[str] = []
    empty_link: list[str] = []
    over_cap: list[str] = []
    for block in marked:
        tmp = str(block.get("tmp", "?"))
        text = str(block.get("text", ""))
        marks = block.get("marks") or []
        if len(marks) > MAX_MARKS_PER_BLOCK:
            over_cap.append(tmp)
        for mark in marks:
            start, end = mark.get("a"), mark.get("b")
            ints = isinstance(start, int) and isinstance(end, int)
            if not ints or not 0 <= start <= end <= len(text):
                out_of_range.append(tmp)
            if mark.get("kind") == "link" and not str(mark.get("target", "")).strip():
                empty_link.append(tmp)
    yield Assertion(
        "every mark satisfies 0 <= a <= b <= len(text)",
        ok=not out_of_range,
        detail=f"blocks: {', '.join(sorted(set(out_of_range))[:5]) or 'none'}",
        fixture=name,
        locus="P9:range",
    )
    yield Assertion(
        "every link mark carries a non-empty target",
        ok=not empty_link,
        detail=f"blocks: {', '.join(sorted(set(empty_link))[:5]) or 'none'}",
        fixture=name,
        locus="P9:link",
    )
    yield Assertion(
        "no block exceeds MAX_MARKS_PER_BLOCK",
        ok=not over_cap,
        detail=f"cap {MAX_MARKS_PER_BLOCK}; over: {', '.join(over_cap[:5])}" if over_cap else "ok",
        fixture=name,
        locus="P9:cap",
    )


def _quad_assertions(subject: Subject, run_result: ParseRun) -> Iterator[Assertion]:
    """P6 when quads exist, P14's absence clause when `spatial = "none"`."""
    parse = subject.card.parse
    assert parse is not None
    name = run_result.fixture.name
    quadded = [b for b in run_result.blocks if b.get("quad") is not None]
    if parse.spatial == "none":
        yield Assertion(
            "spatial = none, and no block carries a quad",
            ok=not quadded,
            detail=f"{len(quadded)} blocks carry a quad",
            fixture=name,
            locus="P14:spatial",
        )
        return
    frames = {int(p.get("page", 0)): p for p in run_result.fragment.pages}
    outside: list[str] = []
    all_zero: list[str] = []
    malformed: list[str] = []
    for block in quadded:
        tmp = str(block.get("tmp", "?"))
        quad = block.get("quad")
        if not isinstance(quad, list) or len(quad) != _QUAD_CORNERS * 2:
            malformed.append(tmp)
            continue
        if all(value == 0 for value in quad):
            all_zero.append(tmp)
            continue
        page = frames.get(int(block.get("page", 0)), {})
        width = int(page.get("w_mpt", 0) or 0)
        height = int(page.get("h_mpt", 0) or 0)
        xs, ys = quad[0::2], quad[1::2]
        if width and height and not _inside(xs, ys, width, height):
            outside.append(tmp)
    yield Assertion(
        "every quad is eight numbers",
        ok=not malformed,
        detail=f"blocks: {', '.join(malformed[:5])}" if malformed else "ok",
        fixture=name,
        locus="P6:shape",
    )
    yield Assertion(
        "no quad is all-zero",
        ok=not all_zero,
        detail=f"blocks: {', '.join(all_zero[:5])}" if all_zero else "ok",
        fixture=name,
        locus="P6:zero",
    )
    yield Assertion(
        f"every quad lies within the page frame plus {QUAD_SLACK_MPT} mpt of slack",
        ok=not outside,
        detail=f"blocks: {', '.join(outside[:5])}" if outside else f"{len(quadded)} quads in frame",
        fixture=name,
        locus="P6:frame",
    )


def _inside(xs: Sequence[Any], ys: Sequence[Any], width: int, height: int) -> bool:
    slack = QUAD_SLACK_MPT
    return all(-slack <= float(x) <= width + slack for x in xs) and all(
        -slack <= float(y) <= height + slack for y in ys
    )


def _absence_assertions(subject: Subject, run_result: ParseRun) -> Iterator[Assertion]:
    """P14's remaining absence clauses: `math = {}`, `assets = "none"`, `confidence = "none"`."""
    parse = subject.card.parse
    assert parse is not None
    name = run_result.fixture.name
    if not parse.math:
        notated = [
            str(b.get("tmp", "?"))
            for b in run_result.blocks
            if (b.get("payload") or {}).get("notation")
        ]
        yield Assertion(
            "math = {}, and no block carries a notation",
            ok=not notated,
            detail=f"blocks: {', '.join(notated[:5])}" if notated else "none",
            fixture=name,
            locus="P14:math",
        )
    if parse.assets == "none":
        assets = [r for r in run_result.fragment.records if r.get("t") == "asset"]
        yield Assertion(
            "assets = none, and the fragment carries zero asset drafts",
            ok=not assets,
            detail=f"{len(assets)} asset records",
            fixture=name,
            locus="P14:assets",
        )
    if parse.confidence == "none":
        scored = [str(b.get("tmp", "?")) for b in run_result.blocks if b.get("score") is not None]
        yield Assertion(
            "confidence = none, and no block carries a score",
            ok=not scored,
            detail=f"blocks: {', '.join(scored[:5])}" if scored else "none",
            fixture=name,
            locus="P14:confidence",
        )


def _achieved_assertions(subject: Subject, runs: Sequence[ParseRun]) -> Iterator[Assertion]:
    """P15: `achieved <= declared` on every key, on every fixture.

    `meets_floor(port, key, declared=<card>, floor=<achieved>)` -- the card must MEET what the
    driver claims to have achieved. The arguments read backwards from `resolve()`'s use and that is
    the point: `resolve()` asks whether a card meets a requirement's floor, and this asks whether a
    card meets its own code's report. One function, two questions, no second ladder.
    """
    parse = subject.card.parse
    assert parse is not None
    port = subject.card.identity.port
    for run_result in runs:
        achieved = run_result.fragment.achieved
        name = run_result.fixture.name
        if not achieved:
            yield Assertion(
                "the doc record carries an achieved block",
                ok=False,
                detail=(
                    "achieved is the driver's self-report of what it delivered on THIS document "
                    "and the whole of P15's left-hand side (03:3010's P24 row)"
                ),
                fixture=name,
                locus="P15",
            )
            continue
        missing = [key for key in _FIFTEEN if key not in achieved]
        yield Assertion(
            "achieved carries all fifteen keys",
            ok=not missing,
            detail=f"missing: {', '.join(missing)}" if missing else "fifteen of fifteen",
            fixture=name,
            locus="P15:keys",
        )
        for key in _FIFTEEN:
            if key not in achieved:
                continue
            declared_value = getattr(parse, key)
            claimed = achieved[key]
            yield Assertion(
                f"achieved.{key} does not exceed the card",
                ok=meets_floor(port, key, declared_value, claimed),
                detail="achieved may be LOWER than the card, never higher (04:2544)",
                fixture=name,
                locus=f"P15:{key}",
                expected=f"card declares {declared_value!r}",
                actual=f"code achieved {claimed!r}",
            )


def _os_kind(block: Mapping[str, Any]) -> str:
    origin = block.get("os") or {}
    return str(origin.get("k", "")) if isinstance(origin, dict) else ""


def _os_part(block: Mapping[str, Any]) -> str:
    origin = block.get("os") or {}
    return str(origin.get("part", "")) if isinstance(origin, dict) else ""
