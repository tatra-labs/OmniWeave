"""`UserPromptSubmit`: the front-load, tiered by verified confidence, and the one G26 measures.

10:1978 is the clearest statement of why this hook exists and what it risks:

> A front-load hook is a stronger adoption lever than any instruction, because it removes the thing
> the agent's reflex grep would have found. It is also the easiest way to burn a user's context on
> nothing, so the gate is tiered by **verified** confidence.

Both halves are load-bearing. The lever only works if the injection is there before the agent
reaches for `grep`; the gate only works if nothing is injected on a guess.

## THE MODULE IS A SHAPE DETECTOR AND NOTHING ELSE

10:1984's three HIGH triggers are each a *shape* plus a *verification*: a `\\bd\\d+#\\d+\\b` cite
that **resolves**, a filename that is **corpus-verified**, a quoted phrase with **at least one FTS5
hit**. The shapes are decidable from the prompt alone and are this module's whole content. The
verifications are store reads and are **injected**, for D410's measured reason: importing
`omniweave_core.store` puts a warm process at 207 ms of a 400 ms self-deadline, and this is the
handler G26 holds to *250 ms p95 warm*.

That split is also what makes the gate testable. A tier decision is a pure function of
`(Shapes, what the probes answered)`, so every row of 10:1982's table is a test with no store in it.

## THE COST COLUMN COUNTS THE INJECTION AND NOT THE VERIFICATION

10:1982 prices HIGH at *"one query"* and MEDIUM at *"one prefix scan"*. A prompt carrying a cite,
a filename and a quoted phrase needs **three** verifications before the tier is known, and then the
query. The column counts the last one. D413.

So `Probes` is one object with four methods rather than four callables, the three verifications are
tried **in the counter order the plan names** -- `-high-cite`, `-high-token`, `-high-fts` -- and the
first that answers wins and stops the rest. That makes the common case one store read, which is what
the cost column claims, and it makes the order a stated decision instead of an accident.

## THE COUNTERS CANNOT MEASURE THE THING THEY EXIST TO MEASURE

10:1990 names seven and says what they are for: *"the data that turns 'is the gate any good' from
vibes into a measured recall rate"*. The two noop counters are `-noop-shape` and `-noop-no-corpus`.

**There is no counter for a prompt that had a shape and verified nothing** -- a cite that did not
resolve, a filename no corpus holds, a phrase FTS5 missed. That outcome is the gate's *false
positive rate*, the one number a precision measurement needs, and it is filed under nothing.
`-noop-shape` is its opposite: no shape at all, the gate correctly quiet. D414.

`_NOOP_UNVERIFIED` is emitted for it here, named rather than folded into `-noop-shape`, because
folding would make the two indistinguishable in exactly the register built to tell them apart.

## COUNTER NAMES ONLY, NEVER PROMPT TEXT

10:1990's rule is absolute and this module is where a prompt could leak: it is the only handler
whose input is the user's own words. `Shapes` holds substrings of the prompt and never reaches an
`Advice.counter`; the tier names are constants; a test asserts that no counter this module can
produce contains anything from the prompt.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Final, Protocol

from omniweave.hooks.envelope import EVENTS, Advice

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping, Sequence

__all__ = [
    "CITE_RE",
    "MEDIUM_MAX_CHARS",
    "PROMPT",
    "Injection",
    "Probes",
    "Shapes",
    "handler",
    "run_prompt",
    "shapes_of",
    "tier_of",
    "unpriced",
]

PROMPT: Final[str] = "prompt"

CITE_RE: Final[re.Pattern[str]] = re.compile(r"\bd\d+#\d+\b")
"""10:1984's regex, verbatim, including its word boundaries.

The boundaries are the whole of its precision: without them `add7#412` and `d7#4123` both match, and
a cite that does not resolve costs a store read on every prompt that mentions a version number.
"""

_PHRASE_RE: Final[re.Pattern[str]] = re.compile(r'"([^"\n]*)"')
"""A quoted span. Straight double quotes only, and **the length bound is not in the pattern.**

Four characters because a two-character quotation is punctuation, and two hundred because an FTS5
match on a paragraph is not a phrase match -- it is the prompt, quoted, which every corpus with
that vocabulary will hit. The plan says *"a quoted phrase"* and prices it at one FTS5 probe; an
unbounded one is a different query with a different cost.

**The bound is applied after pairing and not inside it, because quotes pair left to right.** With
`{4,200}` in the pattern, `say "x" and "the schedule"` skips the two-character `"x"`, resumes at
the quote *after* it, and matches `" and "` -- yielding `and` as a phrase and an FTS5 probe for a
conjunction. One sub-minimum quotation desynchronises every pair after it. Found by a test written
to check the bound, which found the pairing instead.
"""

_PHRASE_MIN: Final[int] = 4
_PHRASE_MAX: Final[int] = 200

_FILENAME_RE: Final[re.Pattern[str]] = re.compile(
    r"(?<![\w./\\-])([\w][\w.-]{0,80}\.[A-Za-z][A-Za-z0-9]{0,7})(?![\w/\\])"
)
"""A filename-shaped token: a stem, a dot, a short alphabetic extension.

Not a path. 10:1984 says *"a corpus-verified filename"*, and a corpus addresses documents by name --
`policy.pdf`, not `./docs/policy.pdf`. The lookbehind refuses a token already inside a path so that
one filename in a path is not probed twice under two spellings.
"""

MEDIUM_MAX_CHARS: Final[int] = 400
"""10:1982's MEDIUM budget: *"a <= 400-char outline list; the agent writes the query."*"""

HIGH_MAX_CHARS: Final[int] = EVENTS["UserPromptSubmit"].cap
"""10:1982's HIGH budget -- *"a full `ow_query` injection, <= 8,000 chars"* -- read, not
retyped.

The same 8,000 is 10:1849's cap for this event and `EVENTS` already holds it. Deriving rather than
respelling is why there is no test here that the two agree: they cannot disagree. What a test does
assert is that the number is 8,000, which is the claim about the plan.
"""

_HIGH_CITE: Final[str] = "high-cite"
#  S105 reads the binding name and sees a credential. The value is 10:1990's counter spelling
#  (`ow-hook-ups-high-token`, the corpus-verified-filename trigger) and renaming the constant away
#  from the name the plan gives it would trade a false positive for a real divergence.
_HIGH_TOKEN: Final[str] = "high-token"  # noqa: S105
_HIGH_FTS: Final[str] = "high-fts"
_MEDIUM_OUTLINE: Final[str] = "medium-outline"
_NOOP_SHAPE: Final[str] = "noop-shape"
_NOOP_NO_CORPUS: Final[str] = "noop-no-corpus"
_NOOP_UNVERIFIED: Final[str] = "noop-unverified"
"""D414. Not one of 10:1990's seven, and the one the recall rate cannot be computed without."""

_MAX_CITES: Final[int] = 8
_MAX_FILENAMES: Final[int] = 8
_MAX_PHRASES: Final[int] = 4
"""Per-prompt probe caps. A prompt is user input and a store read is the expensive thing here.

Without them a pasted stack trace is eighty filename probes inside a 400 ms deadline, which is how
a front-load stops being a front-load: it breaches, emits nothing, and the tier that would have
fired is recorded as `-noop-deadline`.
"""


# ---------------------------------------------------------------------------------------------
# Shapes: everything decidable from the prompt alone.
# ---------------------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Shapes:
    """What a prompt looks like it is about, before anything has been verified.

    **These are substrings of the user's prompt and they must never reach a counter.** 10:1990 is
    the rule; keeping the prompt-derived values in one type with no path to `Advice.counter` is how
    it is held.
    """

    cites: tuple[str, ...] = ()
    filenames: tuple[str, ...] = ()
    phrases: tuple[str, ...] = ()

    def empty(self) -> bool:
        """Whether the gate has nothing to verify: 10:1982's `silent` row, before a store read."""
        return not (self.cites or self.filenames or self.phrases)


def shapes_of(prompt: str) -> Shapes:
    """The three shapes, deduplicated in first-seen order and capped.

    First-seen rather than sorted because the first cite in a prompt is the one the user is asking
    about, and a cap that kept a different eight would probe the wrong ones.
    """
    return Shapes(
        cites=_found(CITE_RE, prompt, _MAX_CITES),
        filenames=_found(_FILENAME_RE, prompt, _MAX_FILENAMES),
        phrases=_phrases(prompt),
    )


def _phrases(prompt: str) -> tuple[str, ...]:
    """Quoted spans, paired first and bounded second. See `_PHRASE_RE`."""
    seen: list[str] = []
    for match in _PHRASE_RE.finditer(prompt):
        value = match.group(1).strip()
        if _PHRASE_MIN <= len(value) <= _PHRASE_MAX and value not in seen:
            seen.append(value)
        if len(seen) >= _MAX_PHRASES:
            break
    return tuple(seen)


def _found(pattern: re.Pattern[str], prompt: str, cap: int) -> tuple[str, ...]:
    seen: list[str] = []
    for match in pattern.finditer(prompt):
        value = (match.group(1) if pattern.groups else match.group(0)).strip()
        if value and value not in seen:
            seen.append(value)
        if len(seen) >= cap:
            break
    return tuple(seen)


# ---------------------------------------------------------------------------------------------
# The store seam. D410: injected, never imported.
# ---------------------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Injection:
    """What a probe produced: the text to inject and the ledger commit that must follow the flush.

    `after_emit` travels to `Outcome.after_emit` untouched and is called by the `__main__` after
    stdout is flushed. 10:2004 requires that ordering and D384 measured why it is made structural:
    a ledger written before the bytes leave claims an emission the model never saw.
    """

    text: str = ""
    after_emit: Callable[[], None] | None = None


class Probes(Protocol):
    """The four store reads 10:1982's table needs, as a seam rather than an import.

    One object rather than four callables because the three verifications share a connection, and
    10:1886 clause 3 makes every hook store read go through the `connect_readonly` ladder -- a
    ladder taken once rather than three times.
    """

    def resolve(self, cites: Sequence[str]) -> Sequence[str]:
        """Which of these cites resolve. 10:1984's first HIGH trigger."""
        ...

    def known(self, filenames: Sequence[str]) -> Sequence[str]:
        """Which of these filenames a corpus holds. The second."""
        ...

    def search(self, phrases: Sequence[str]) -> Sequence[str]:
        """Which of these phrases have at least one FTS5 hit. The third."""
        ...

    def outline(self, prompt: str) -> str:
        """MEDIUM's one prefix scan: titles and TOC entries, `""` when nothing matches."""
        ...

    def query(self, seed: Sequence[str], trigger: str) -> Injection:
        """HIGH's one `ow_query`, rendered through SV19 and charged to the ledger. 10:2003."""
        ...


# ---------------------------------------------------------------------------------------------
# The tier decision. A pure function of the shapes and what the probes answered.
# ---------------------------------------------------------------------------------------------


def tier_of(shapes: Shapes, probes: Probes | None) -> tuple[str, Injection]:
    """`(counter suffix, what to inject)`. 10:1982's table, read top to bottom.

    **The three HIGH triggers are tried in the plan's own counter order and the first wins.**
    10:1990 lists them `-high-cite`, `-high-token`, `-high-fts`, which is also strongest to
    weakest: a cite that resolves is an exact address, a filename is a document, and an FTS5 hit is
    a vocabulary match. Trying all three would cost three store reads for a tier the plan prices at
    one (D413).

    MEDIUM is reached only when no HIGH trigger verified, and `silent` when MEDIUM found nothing.
    """
    if probes is None:
        return _NOOP_NO_CORPUS, Injection()
    if shapes.empty():
        return _NOOP_SHAPE, Injection()

    for trigger, candidates, probe in (
        (_HIGH_CITE, shapes.cites, probes.resolve),
        (_HIGH_TOKEN, shapes.filenames, probes.known),
        (_HIGH_FTS, shapes.phrases, probes.search),
    ):
        if not candidates:
            continue
        verified = tuple(_strings(probe(candidates)))
        if verified:
            injection = probes.query(verified, trigger)
            if injection.text:
                return trigger, Injection(injection.text[:HIGH_MAX_CHARS], injection.after_emit)

    return _NOOP_UNVERIFIED, Injection()


def medium_of(prompt: str, probes: Probes | None) -> tuple[str, Injection]:
    """MEDIUM's prefix scan, capped at 400 characters and carrying no content. 10:1982.

    **No `after_emit` and no ledger entry.** 10:2003 charges the HIGH injection to the ledger
    because it *is* an Answer; an outline is a list of titles the agent may then query for itself,
    so ledgering it would suppress the very query it exists to provoke.
    """
    if probes is None:
        return _NOOP_NO_CORPUS, Injection()
    outline = str(probes.outline(prompt) or "")
    if not outline:
        return _NOOP_UNVERIFIED, Injection()
    return _MEDIUM_OUTLINE, Injection(outline[:MEDIUM_MAX_CHARS])


def _strings(values: object) -> tuple[str, ...]:
    """A probe's answer as strings. A probe is injected code and may return anything."""
    if isinstance(values, str) or not isinstance(values, (list, tuple, set, frozenset)):
        return ()
    return tuple(str(value) for value in values if value)


# ---------------------------------------------------------------------------------------------
# The handler.
# ---------------------------------------------------------------------------------------------


def run_prompt(payload: Mapping[str, Any], *, probes: Probes | None) -> Advice:
    """10:1982's three tiers, in order, and never more than one store read for the common prompt.

    No `<sessions>` root and no session key: the ledger commit is built by the probe that made
    the injection, because only that probe knows what it charged. This handler carries the commit
    and never constructs one, which is why it needs neither.
    """
    prompt = str(payload.get(PROMPT, ""))
    if not prompt.strip():
        return Advice(counter=_NOOP_SHAPE)

    shapes = shapes_of(prompt)
    trigger, injection = tier_of(shapes, probes)
    if injection.text:
        return Advice(text=injection.text, counter=trigger, after_emit=injection.after_emit)
    if trigger in (_NOOP_NO_CORPUS, _NOOP_SHAPE):
        return Advice(counter=trigger)

    medium, outline = medium_of(prompt, probes)
    if outline.text:
        return Advice(text=outline.text, counter=medium)
    return Advice(counter=_NOOP_UNVERIFIED)


def handler(probes: Probes | None) -> Callable[[Mapping[str, Any]], Advice]:
    """`run_prompt` bound to a set of probes, in the shape `envelope.run()` takes."""

    def bound(payload: Mapping[str, Any]) -> Advice:
        return run_prompt(payload, probes=probes)

    return bound


def unpriced() -> tuple[str, ...]:
    """What this gate does against a reading rather than against a statement."""
    return (
        "the cost of verifying. 10:1982 prices HIGH at 'one query' and MEDIUM at 'one prefix "
        "scan', and a prompt carrying all three shapes needs three verifications before the tier "
        "is known. The triggers are tried in the plan's counter order and the first wins, which "
        "makes the common case one read and the order a decision (D413)",
        "the counter for a shape that verified nothing. 10:1990's seven have `-noop-shape` (no "
        "shape) and `-noop-no-corpus` (no corpus), and nothing for a cite that did not resolve -- "
        "which is the gate's false-positive rate and the half of a recall measurement that is "
        "missing (D414)",
        "what a quoted phrase is. 10:1984 says 'a quoted phrase with >= 1 FTS5 hit' and names no "
        "bounds; an unbounded one makes the FTS5 probe a different query with a different cost, "
        "so this module bounds it at 4..200 characters and straight quotes",
        "whether MEDIUM's outline is charged to the ledger. 10:2003 charges the HIGH injection "
        "because it is an Answer and says nothing about the outline; ledgering a list of titles "
        "would suppress the query it exists to provoke, so it is not charged here",
        "the deadline this gate is measured by. G26 holds `ow hook prompt` to 250 ms p95 warm, "
        "and D410 measured a warm process at 207 ms before a handler runs when the store is "
        "imported in-process. The probes are injected so that cost is the caller's to place",
    )
