"""`PreCompact`: two writes, no output, always exit 0, and a briefing with no schema behind it.

10:1927 is the reason this event exists at all, and it is a correction of something shipped:

> **`PreCompact` has no model-facing channel at all** -- no `additionalContext`, and hosts
> document that a `PreCompact` hook's `systemMessage` is discarded. A design that emits the
> restoration briefing here writes into a field nobody receives, which is precisely what
> jcodemunch shipped for a release line (`cli/hooks/snapshot.py:66-80`).

So the compaction play is split: `PreCompact` **writes two files and says nothing**, and
`SessionStart` emits what it wrote. `envelope.emission()` already enforces the silence:
`PreCompact` has `cap = 0` and returns `""` whatever it is handed.

## THE FIRST WRITE IS THE CORRECTNESS CONDITION FOR DEDUP, NOT BOOKKEEPING

`<key>.compacted` is what makes the emission ledger safe. Everything the server withheld as
*"already sent earlier in this conversation"* is about to leave the context window, and 10:1937
says why a pointer is then worse than a resend: *"a pointer to content the agent no longer holds
is strictly worse than re-sending it: the agent Reads the file."* -- which is the one behaviour
this framework exists to remove. The server reads the marker with one `stat` **on every call** and
records `Degradation(kind="ledger_reset_by_compaction")`.

That write is fully specified and this module does it verbatim.

## THE SECOND WRITE HAS NO SCHEMA, AND THE PLAN NEVER NOTICES

`render_briefing(read_journal(key, max_age_min=240))` is the whole of 10:1943, and the briefing it
renders has four lines drawn from four different subsystems -- corpora and their freshness, cites
delivered, parse gaps, artefacts in flight. **The plan declares no journal record schema
anywhere.** 10:1911 says *"one JSON object per line, each record capped at 4,096 bytes"* and names
not one field, and 10:1882 -- the clause that makes the server the writer -- names none either.
The only statement of what a record must carry is the rendered *example* at 10:1953, read
backwards. D405.

So the four record kinds are declared here, derived from that example and named in `KINDS`, and a
test parses the example out of the plan and asserts every line of it can be produced. That is the
`EVENTS` treatment from W7.4a applied to a shape instead of a table: an amended example fails a
test rather than becoming a second opinion about a format two distributions write.

## THE STATED REASON FOR FREEZING THE BRIEFING IS NOT THE TRUE ONE

10:1941: *"Written now, because after compaction the transcript that names the corpora and cites
is gone."* The briefing is not rendered from the transcript. It is rendered from
`read_journal(key, ...)`, which is `<sessions>/<key>.jsonl` -- a file, on disk, that compaction
does not touch and the sweep does not reach for 24 hours. D406.

And the freeze cannot serve the other two sources. 10:1947 has `SessionStart` emitting a briefing
for `source in {compact, resume, fork}`, and **a resume and a fork never fire `PreCompact`**, so
for two of the three there is no frozen file to emit. Whatever renders those must render live --
which means `render_briefing` is `SessionStart`'s function too, and the freeze is an optimisation
for the one case that needed it least.

Which is why `render_briefing()` returns the **body** and `briefing()` puts the heading on: the
heading is `restored after compaction` here and two other strings there, so a file frozen with its
heading attached would be wrong for two thirds of its readers. D407.
"""

from __future__ import annotations

from types import MappingProxyType
from typing import TYPE_CHECKING, Any, Final

from omniweave.hooks.envelope import Advice, session_key
from omniweave.hooks.session import READ_AGE_MIN, read, write_marker

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable, Mapping, Sequence
    from pathlib import Path

__all__ = [
    "ARTEFACT",
    "BRIEFING",
    "BRIEFING_MAX_CHARS",
    "CITE",
    "COMPACTED",
    "CORPUS",
    "GAP",
    "KIND",
    "KINDS",
    "SOURCE_LABELS",
    "TRIGGER",
    "briefing",
    "handler",
    "render_briefing",
    "run_precompact",
    "unfrozen",
]

# ---------------------------------------------------------------------------------------------
# The two files. 10:1938 and 10:1943.
# ---------------------------------------------------------------------------------------------

COMPACTED: Final[str] = "compacted"
BRIEFING: Final[str] = "briefing"
TRIGGER: Final[str] = "trigger"
UNKNOWN_TRIGGER: Final[str] = "unknown"

BRIEFING_MAX_CHARS: Final[int] = 4_000
"""`EVENTS["SessionStart"].cap`, respelled so the freeze is bounded by what will emit it.

The cap belongs to the emitting event and the text is produced by this one, which is the only
reason it is here twice. A test asserts the two numbers are equal; a briefing frozen above the cap
would be truncated at emission, and truncation takes the tail -- where the artefacts and the gaps
are, and where a slice can land mid-cite.
"""

# ---------------------------------------------------------------------------------------------
# The record kinds. D405: derived from 10:1953's example, because nothing declares them.
# ---------------------------------------------------------------------------------------------

KIND: Final[str] = "kind"
CORPUS: Final[str] = "corpus"
CITE: Final[str] = "cite"
GAP: Final[str] = "gap"
ARTEFACT: Final[str] = "artefact"

KINDS: Final[Mapping[str, tuple[str, ...]]] = MappingProxyType(
    {
        CORPUS: ("corpus", "version", "stale"),
        CITE: ("corpus", "ref"),
        GAP: ("uri", "pages", "span", "reason"),
        ARTEFACT: ("name", "gate", "units"),
    }
)
"""The four record shapes 10:1953's four lines require, and the plan's only statement of them.

Read off the example backwards, field by field: *"handbook@41 (fresh)"* is a corpus, a version and
a stale count; *"handbook:d7#412"* is a corpus and a ref; *"4 pages of 2024-appendix.pdf
(p.12-15) -- OCR deferred"* is a uri, a page count, a span and a reason;
*"deck/2025-q1-benefits (gate: manual_required, 2 units)"* is a name, a gate and a unit count.

**Every one of these is written by `omniweave_serve` and read here**, which is D398's layers row
with a schema attached: the writer and the reader of this shape are in two distributions that may
not import each other, and the shape is written down in neither.
"""

SOURCE_LABELS: Final[Mapping[str, str]] = MappingProxyType(
    {
        "compact": "restored after compaction",
        "resume": "restored on resume",
        "fork": "carried into this fork",
    }
)
"""10:1947's three labels. `startup` and `clear` are absent -- 10:1974 returns 0 for those two."""

_HEADING: Final[str] = "## omniweave session state ({label})"
_CITE_HEADING: Final[str] = "Cites delivered before compaction, still resolvable and still exact:"
_CITE_NOTE: Final[str] = (
    "  These are NOT in your context any more. Resolve one with ow_open, do NOT Read the file."
)
_FRESH: Final[str] = "fresh"
_REFRESH: Final[str] = "`ow add` to refresh"

_TIER_FROZEN: Final[str] = "frozen"
_TIER_MARKED: Final[str] = "marked-no-briefing"
_TIER_NO_KEY: Final[str] = "noop-no-key"
_TIER_NO_WRITE: Final[str] = "noop-no-write"

_CORPORA_INDEX: Final[int] = 0
_GAPS_INDEX: Final[int] = 2
_ARTEFACTS_INDEX: Final[int] = 3


# ---------------------------------------------------------------------------------------------
# Rendering.
# ---------------------------------------------------------------------------------------------


def render_briefing(
    records: Iterable[Mapping[str, Any]],
    *,
    limit: int = BRIEFING_MAX_CHARS,
) -> str:
    """The briefing **body**, without the heading, bounded by `limit`. 10:1953.

    The heading is not here because it is not knowable here: `SessionStart` labels by source and
    two of its three sources never fire this event (D407). `briefing()` puts it on.

    **Cites are never dropped and everything else may be.** 10:1968 is explicit about where the
    value is -- *"a briefing that re-injected the passages would spend the compaction budget on
    the material compaction just removed; a briefing that names them costs ~40 characters each and
    turns the next `ow_open` into a one-call recovery"*. So when the body will not fit, the
    artefacts go first, then the gaps, then the corpora, and the cite block is the last thing
    standing. The plan states no priority at all, which is D408: the example is one rendering of a
    session small enough to fit.
    """
    grouped = _group(records)
    sections = [
        _corpora(grouped[CORPUS]),
        _cites(grouped[CITE]),
        _gaps(grouped[GAP]),
        _artefacts(grouped[ARTEFACT]),
    ]
    droppable = [_ARTEFACTS_INDEX, _GAPS_INDEX, _CORPORA_INDEX]
    body = "\n".join(text for text in sections if text)
    while len(body) > limit and droppable:
        sections[droppable.pop(0)] = ""
        body = "\n".join(text for text in sections if text)
    return body[:limit]


def briefing(body: str, source: str) -> str:
    """The heading for `source` plus `body`, or `""` for a source with no briefing. 10:1947.

    `startup` and `clear` return `""` rather than an unlabelled briefing, which is 10:1974's rule
    and its reason: *"an unrelated session's journal would present stale files as this session's
    focus."* A missing label is not a formatting problem, it is the wrong session.
    """
    label = SOURCE_LABELS.get(source, "")
    if not label or not body:
        return ""
    return _HEADING.format(label=label) + "\n\n" + body


def strip_cites(body: str) -> str:
    """A rendered body with its three cite lines removed. The block's shape lives here, not away.

    `sessionstart` needs this because 10:1970 requires every cite re-verified before emission and a
    *frozen* briefing is text with no cites to verify -- only a line that contains them (D409). It
    is here rather than there because the heading, the refs line and the `ow_open` note are this
    module's constants, and a second spelling of them somewhere else would be a second answer to
    what a cite block looks like.

    The refs line is found by its position under the heading and the note by its own text, so a
    briefing whose other sections moved still loses exactly the block that could not be checked.

    `split("\\n")` and never `splitlines()`. `render_briefing` joins on `\\n` and nothing else, and
    `splitlines()` additionally breaks on U+2028, U+2029 and U+0085 -- any of which can reach a
    record through a corpus name, survive `_text()` (which strips only CR and LF) and shift every
    line after it by one. That would make `skip` drop the wrong line, which is how a cite block
    loses its heading and keeps its refs.
    """
    kept: list[str] = []
    skip = False
    for line in body.split("\n"):
        if skip:
            skip = False
            continue
        if line.startswith(_CITE_HEADING):
            skip = True
            continue
        if line == _CITE_NOTE:
            continue
        kept.append(line)
    return "\n".join(kept)


def _group(records: Iterable[Mapping[str, Any]]) -> Mapping[str, list[Mapping[str, Any]]]:
    """Records by kind, in journal order, and anything unrecognised silently dropped.

    Dropped rather than counted, because an unknown kind is the *expected* state of a schema the
    plan never declared (D405): the server will write kinds this module has not heard of, and a
    briefing that failed on one would be a hook breaking on a field addition.
    """
    grouped: dict[str, list[Mapping[str, Any]]] = {kind: [] for kind in KINDS}
    for record in records:
        kind = record.get(KIND)
        if isinstance(kind, str) and kind in grouped:
            grouped[kind].append(record)
    return grouped


def _corpora(records: Sequence[Mapping[str, Any]]) -> str:
    """`Corpora touched: handbook@41 (fresh), contracts@12 (2 documents stale - ...)`.

    Last record wins per corpus: the journal is append-only and a corpus re-indexed mid-session
    appears twice, where the later row is the true one.
    """
    latest: dict[str, Mapping[str, Any]] = {}
    for record in records:
        name = _text(record.get("corpus"))
        if name:
            latest[name] = record
    if not latest:
        return ""
    parts: list[str] = []
    for name, record in latest.items():
        version = _text(record.get("version"))
        stale = _count(record.get("stale"))
        plural = "s" if stale > 1 else ""
        state = _FRESH if stale <= 0 else f"{stale} document{plural} stale — {_REFRESH}"
        head = f"{name}@{version}" if version else name
        parts.append(f"{head} ({state})")
    return "Corpora touched: " + ", ".join(parts)


def _cites(records: Sequence[Mapping[str, Any]]) -> str:
    """The cite block: one group per corpus, refs joined by a space, groups by a middle dot.

    Deduplicated in first-seen order rather than sorted. A cite delivered twice is one cite, and
    the order the session met them in is the only ordering that carries information -- a sort by
    ref would put `d31#88` before `d7#412` and tell the agent something untrue about the session.
    """
    seen: dict[str, list[str]] = {}
    for record in records:
        corpus, ref = _text(record.get("corpus")), _text(record.get("ref"))
        if corpus and ref and ref not in seen.setdefault(corpus, []):
            seen[corpus].append(ref)
    if not seen:
        return ""
    joined = " · ".join(f"{corpus}:{' '.join(refs)}" for corpus, refs in seen.items())
    return f"{_CITE_HEADING}\n  {joined}\n{_CITE_NOTE}"


def _gaps(records: Sequence[Mapping[str, Any]]) -> str:
    """10:1964's line: `Open gaps in what you asked about: 4 pages of <uri> (<span>) - <reason>`."""
    parts: list[str] = []
    for record in records:
        uri = _text(record.get("uri"))
        if not uri:
            continue
        pages, span = _count(record.get("pages")), _text(record.get("span"))
        reason = _text(record.get("reason")).replace("_", " ")
        entry = f"{pages} pages of {uri}" if pages else uri
        if span:
            entry += f" ({span})"
        if reason:
            entry += f" — {reason}"
        parts.append(entry)
    return "Open gaps in what you asked about: " + "; ".join(parts) + "." if parts else ""


def _artefacts(records: Sequence[Mapping[str, Any]]) -> str:
    """`Artefacts in flight: deck/2025-q1-benefits (gate: manual_required, 2 units)`."""
    parts: list[str] = []
    for record in records:
        name = _text(record.get("name"))
        if not name:
            continue
        gate, units = _text(record.get("gate")), _count(record.get("units"))
        detail = ", ".join(
            filter(None, (f"gate: {gate}" if gate else "", f"{units} units" if units else ""))
        )
        parts.append(f"{name} ({detail})" if detail else name)
    return "Artefacts in flight: " + ", ".join(parts) if parts else ""


def _text(value: object) -> str:
    """A scalar as a line-safe string. A newline in a record would forge a briefing section."""
    if value is None or isinstance(value, dict | list | tuple):
        return ""
    return str(value).replace("\n", " ").replace("\r", " ").strip()


def _count(value: object) -> int:
    return value if isinstance(value, int) and not isinstance(value, bool) else 0


# ---------------------------------------------------------------------------------------------
# The handler. 10:1932 -- two writes, no output, always exit 0.
# ---------------------------------------------------------------------------------------------


def run_precompact(payload: Mapping[str, Any], *, root: Path | None, wall_ns: int) -> Advice:
    """10:1932's `run_precompact`, verbatim in name, as an `Advice` rather than an `int`.

    **The plan's spelling is load-bearing and this is why.** The module is `precompact.py` (10:1931)
    and a function called `precompact` inside it collides with it: `omniweave.hooks.__init__`
    re-exports the function, which shadows the submodule, so `import omniweave.hooks.precompact`
    hands back a function. A test found that by doing exactly this. 10:1933 already spells it
    `run_precompact` and the collision is the reason to keep that spelling rather than shorten it.

    The order is the plan's and it is not arbitrary: the **marker first**, because it is the
    correctness condition for the ledger and the briefing is a convenience. A process killed
    between the two writes leaves a marker with no briefing, which costs one session a restoration
    note; the reverse leaves a briefing whose ledger was never reset, which is the
    pointer-to-absent-content failure 10:1937 calls *"strictly worse than re-sending it"*.

    `root is None` is D403's deployment -- no `omniweave.toml`, so no `<sessions>` -- and it
    returns the same silent tier as a payload with no session id.
    """
    key = session_key(payload)
    if not key or root is None:
        return Advice(counter=_TIER_NO_KEY)
    marked = write_marker(
        root,
        key,
        COMPACTED,
        {"at_ns": wall_ns, "reason": _text(payload.get(TRIGGER)) or UNKNOWN_TRIGGER},
    )
    if not marked:
        return Advice(counter=_TIER_NO_WRITE)
    journal = read(root, key, now_ns=wall_ns, max_age_min=READ_AGE_MIN)
    body = render_briefing(journal.records)
    if not body or not write_marker(root, key, BRIEFING, {"body": body}):
        return Advice(counter=_TIER_MARKED)
    return Advice(counter=_TIER_FROZEN)


def handler(root: Path | None, wall_ns: Callable[[], int]) -> Callable[[Mapping[str, Any]], Advice]:
    """`run_precompact` bound to a root and a clock, in the shape `envelope.run()` takes.

    The clock arrives as a callable and not as a reading, because `run()` calls the handler and
    the marker's `at_ns` must be the moment of compaction rather than the moment this process
    started.
    """

    def bound(payload: Mapping[str, Any]) -> Advice:
        return run_precompact(payload, root=root, wall_ns=wall_ns())

    return bound


def unfrozen() -> tuple[str, ...]:
    """What this handler renders against a reading rather than against a statement."""
    return (
        "the journal record schema. 10:1911 caps a record at 4,096 bytes and names no field; "
        "10:1882 makes the server the writer and names none either. `KINDS` is read backwards "
        "out of 10:1953's rendered example, which is the plan's only statement of the shape "
        "(D405), and the writer is in a distribution that may not import this one (D398)",
        "why the briefing is frozen. 10:1941 says the transcript is gone after compaction, but "
        "the briefing is rendered from the journal, which is a file compaction does not touch "
        "(D406)",
        "who renders the briefing for `resume` and `fork`. Neither fires `PreCompact`, so neither "
        "has a frozen file, and 10:1947 emits a briefing for all three sources (D407)",
        "which sections a briefing drops when it will not fit. The example is one rendering of a "
        "session small enough to fit, and 10:1968 argues the value is in the cites without "
        "saying so as an ordering (D408)",
        "re-verifying cites against the store. 10:1970 requires it *before emission*, which is "
        "`SessionStart`'s call and not this one -- so a cite frozen here may be retired by the "
        "time it is read, and nothing in this module can tell",
    )
