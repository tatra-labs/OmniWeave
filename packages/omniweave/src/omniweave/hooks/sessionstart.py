"""`SessionStart`: the one hook that speaks, and the only one that must read the store to do it.

10:1954 gives this event the briefing `PreCompact` froze, capped at 4,000 characters and labelled by
source. Two clauses make it the hardest of the six, and they pull against each other.

## THE CLAUSE THAT CANNOT BE SATISFIED ON THE PATH THE PLAN BUILT

10:1970, one sentence:

> **Every cite listed is re-verified against the store before emission**, so a cite retired between
> the two events is dropped with a one-line note rather than handed back as live.

10:1943, one line, written four paragraphs earlier:

```python
atomic_write(SESSIONS / f"{key}.briefing", render_briefing(read_journal(key, max_age_min=240)))
```

**The frozen artefact is rendered text and re-verification needs structure.** A cite inside
`handbook:d7#412 d7#418 d31#88 · contracts:d3#77` cannot be checked against a store and dropped
without parsing that line back into the records it was rendered from -- which is to say, without
undoing the freeze. The two clauses are individually reasonable and jointly unimplementable on the
artefact the plan specifies. D409.

So this module renders from the **journal** and treats `<key>.briefing` as a fallback it cannot
vouch for. That also settles D407: `resume` and `fork` never fire `PreCompact` and have no frozen
file at all, so a live render was always required for two of the three sources. One path, three
sources, and verification possible on all of them.

## THE OTHER CLAUSE IS A BUDGET, AND IT IS ALREADY SPENT

A store read means `omniweave_core.store`, which is one of G17's **nine lazy subpackages** -- the
gate exists precisely so that `import omniweave_core` does not pay it. Measured on this machine,
median of seven, warm:

| what a process has imported | wall clock |
|---|---:|
| a bare interpreter | 31.5 ms |
| `+ omniweave.hooks.envelope`, `.session` | 81.7 ms |
| `+ omniweave_core.config` (D401) | 102.9 ms |
| `+ omniweave_core.store.sqlite` | **207.1 ms** |

**207 ms of a 400 ms self-deadline, before the handler runs a line**, and that is the warm figure.
10:1844's deadline is stated for all six handlers; this is the handler that cannot avoid the import.
D410.

Which is why the verifier is **injected and never imported here**. `Verify` is a callable this
module declares and a caller supplies, so the import decision belongs to the four-line `__main__`
that knows whether a store is reachable, and this module stays as cheap as `precompact.py`. A test
asserts the import list.

## WHAT A MISSING VERIFIER MEANS, AND WHY IT IS NOT "EMIT ANYWAY"

`verify=None` is a deployment with no reachable store, and 10:1970 is unconditional. So the cite
block is **dropped whole** and the briefing says so in one line, which is the treatment that clause
already prescribes for a single retired cite. The alternative -- emitting unverified cites -- hands
the agent addresses that may resolve to nothing, and 10:1937 is explicit that a dead pointer is
*"strictly worse than re-sending it"*.

The briefing survives without its cites; it is worth less, and it says how much less.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any, Final

from omniweave.hooks.envelope import Advice, session_key
from omniweave.hooks.precompact import (
    BRIEFING,
    BRIEFING_MAX_CHARS,
    CITE,
    KIND,
    SOURCE_LABELS,
    briefing,
    render_briefing,
    strip_cites,
)
from omniweave.hooks.session import READ_AGE_MIN, SWEEP_AGE_S, Journal, read, sweep

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping, Sequence
    from collections.abc import Set as AbstractSet
    from pathlib import Path

__all__ = [
    "SILENT_SOURCES",
    "SOURCE",
    "Verify",
    "handler",
    "retired_note",
    "run_sessionstart",
    "unverifiable",
    "verified",
]

SOURCE: Final[str] = "source"
SILENT_SOURCES: Final[tuple[str, ...]] = ("startup", "clear")
"""10:1974, and its reason: *"an unrelated session's journal would present stale files as this
session's focus."* These two return 0 with no output, and they are not a subset of a cap check --
`SessionStart` has a channel, so nothing downstream would stop them."""

_NO_STORE_NOTE: Final[str] = (
    "  Cites are withheld: the store could not be read, so none could be re-verified."
)
_RETIRED_ONE: Final[str] = "  1 cite delivered earlier has been retired since and is not listed."
_RETIRED_MANY: Final[str] = (
    "  {count} cites delivered earlier have been retired since and are not listed."
)

_TIER_EMITTED: Final[str] = "briefing"
_TIER_FROZEN_FALLBACK: Final[str] = "briefing-unverified"
_TIER_NO_KEY: Final[str] = "noop-no-key"
_TIER_SOURCE: Final[str] = "noop-source"
_TIER_EMPTY: Final[str] = "noop-empty"

if TYPE_CHECKING:
    Verify = Callable[[Sequence[tuple[str, str]]], AbstractSet[tuple[str, str]]]
    """`(corpus, ref)` pairs in, the ones that still resolve out. Injected, never imported.

    A batch call and not one per cite, because 10:1886 clause 3 makes every hook store read go
    through the `connect_readonly` ladder and a ladder taken once is a ladder taken once. The
    signature is the whole of this module's dependency on the store, and D410 is why it is a
    signature rather than an import.
    """


# ---------------------------------------------------------------------------------------------
# Verification. 10:1970.
# ---------------------------------------------------------------------------------------------


def verified(
    records: Sequence[Mapping[str, Any]],
    verify: Verify | None,
) -> tuple[tuple[Mapping[str, Any], ...], int]:
    """`(records with retired cites removed, how many were removed)`. Non-cite records pass through.

    `verify=None` removes **every** cite rather than none. 10:1970 is unconditional and a briefing
    that cannot check its cites has not checked them; the count it returns is the number withheld,
    so the note downstream is true either way.

    A verifier that raises is treated as a verifier that verified nothing. This is the one place a
    hook calls into code it does not own, and 10:1842 makes every failure path a silent exit 0 --
    an exception here would take the briefing with it.
    """
    pairs = tuple(
        (str(record.get("corpus", "")), str(record.get("ref", "")))
        for record in records
        if record.get(KIND) == CITE
    )
    if not pairs:
        return tuple(records), 0
    if verify is None:
        live: AbstractSet[tuple[str, str]] = frozenset()
    else:
        try:
            live = verify(pairs)
        except Exception:  # 10:1842 -- a failure here must not cost the whole briefing.
            live = frozenset()
    kept = tuple(
        record
        for record in records
        if record.get(KIND) != CITE
        or (str(record.get("corpus", "")), str(record.get("ref", ""))) in live
    )
    return kept, sum(1 for pair in pairs if pair not in live)


def retired_note(count: int, *, had_store: bool) -> str:
    """The one line 10:1970 asks for when a cite is dropped, or `""` when nothing was.

    Two sentences rather than one, because the two cases are different facts. *"Retired"* says the
    store was asked and answered; *"withheld"* says it was never reached, and an agent that reads
    the first when the second is true will conclude a corpus changed under it.
    """
    if count <= 0:
        return ""
    if not had_store:
        return _NO_STORE_NOTE
    return _RETIRED_ONE if count == 1 else _RETIRED_MANY.format(count=count)


# ---------------------------------------------------------------------------------------------
# The handler.
# ---------------------------------------------------------------------------------------------


def run_sessionstart(
    payload: Mapping[str, Any],
    *,
    root: Path | None,
    wall_ns: int,
    verify: Verify | None = None,
    swept: bool = True,
) -> Advice:
    """The briefing for `compact`, `resume` and `fork`; nothing for `startup` and `clear`.

    **The sweep happens before the source check and not after.** 10:1918 gives `SessionStart` the
    24-hour sweep *"plus an oldest-first eviction"* and says why it cannot wait for `SessionEnd`:
    *"a host that crashes never fires `SessionEnd`, and a directory that only grows is a slow leak
    in the one place a user never looks."* A `startup` session is the most common one there is, so
    hanging the sweep off the sources that speak would be hanging it off the rare case.

    **The render is from the journal for every source.** D407: `resume` and `fork` never fired
    `PreCompact`, so they have no frozen file; D409: the frozen file is text and 10:1970's
    re-verification needs records. One live path is the only arrangement in which the briefing is
    both available and verified.
    """
    key = session_key(payload)
    if not key or root is None:
        _housekeep(root, wall_ns=wall_ns, swept=swept)
        return Advice(counter=_TIER_NO_KEY)
    source = str(payload.get(SOURCE, ""))
    if source not in SOURCE_LABELS:
        _housekeep(root, wall_ns=wall_ns, swept=swept)
        return Advice(counter=_TIER_SOURCE)

    journal = read(root, key, now_ns=wall_ns, max_age_min=READ_AGE_MIN)
    advice = _briefing_advice(journal, root=root, key=key, source=source, verify=verify)
    _housekeep(root, wall_ns=wall_ns, swept=swept)
    return advice


def _housekeep(root: Path | None, *, wall_ns: int, swept: bool) -> None:
    """10:1918's sweep, run AFTER the briefing and never before it.

    The plan gives `SessionStart` the sweep and does not order it against the read, and the order
    is not free: the sweep removes by filesystem mtime and the read selects by a record's `at_ns`,
    which are two clocks. A handler that swept first would hand its own journal to the 24-hour rule
    and then read the file it had just removed -- and it would do that silently, because an empty
    journal is the normal state of a new session.
    """
    if root is not None and swept:
        sweep(root, now_ns=wall_ns, max_age_s=SWEEP_AGE_S)


def _briefing_advice(
    journal: Journal,
    *,
    root: Path,
    key: str,
    source: str,
    verify: Verify | None,
) -> Advice:
    """The briefing for one source, from the journal if it has records and the freeze if not."""
    records = journal.records
    if records:
        kept, dropped = verified(records, verify)
        note = retired_note(dropped, had_store=verify is not None)
        body = render_briefing(kept, limit=BRIEFING_MAX_CHARS - len(note) - 1)
        if note:
            body = f"{body}\n{note}" if body else note.strip()
        text = briefing(body, source)
        return Advice(text=text, counter=_TIER_EMITTED) if text else Advice(counter=_TIER_EMPTY)

    frozen = _frozen_body(root, key)
    if not frozen:
        return Advice(counter=_TIER_EMPTY)
    text = briefing(_without_cites(frozen), source)
    return Advice(text=text, counter=_TIER_FROZEN_FALLBACK) if text else Advice(counter=_TIER_EMPTY)


def _frozen_body(root: Path, key: str) -> str:
    """`<key>.briefing`'s body, or `""`. The fallback, reached only when the journal is gone.

    Which is a narrow window and worth naming: the journal is swept at 24 h and the briefing is
    swept by the same rule (D402), so the case this covers is a journal rotated past the age bound
    while its briefing is still inside it.
    """
    try:
        raw = (root / f"{key}.{BRIEFING}").read_text(encoding="utf-8")
    except OSError:
        return ""
    try:
        parsed = json.loads(raw)
    except ValueError:
        return ""
    body = parsed.get("body") if isinstance(parsed, dict) else None
    return body if isinstance(body, str) else ""


def _without_cites(body: str) -> str:
    """The frozen body with its cite block gone and one line saying why. D409."""
    return strip_cites(body) + "\n" + _NO_STORE_NOTE


def handler(
    root: Path | None,
    wall_ns: Callable[[], int],
    *,
    verify: Verify | None = None,
) -> Callable[[Mapping[str, Any]], Advice]:
    """`run_sessionstart` bound to a root, a clock and a verifier, in `envelope.run()`'s shape."""

    def bound(payload: Mapping[str, Any]) -> Advice:
        return run_sessionstart(payload, root=root, wall_ns=wall_ns(), verify=verify)

    return bound


def unverifiable() -> tuple[str, ...]:
    """What this handler emits against a reading rather than against a statement."""
    return (
        "re-verifying a frozen briefing. 10:1970 requires every cite re-verified before emission "
        "and 10:1943 freezes rendered text, which has no cites to verify -- only a line that "
        "contains them. The frozen path therefore emits without its cite block (D409)",
        "the import budget. A store read is `omniweave_core.store`, one of G17's nine lazy "
        "subpackages, and importing it puts a warm process at 207 ms of a 400 ms self-deadline "
        "before the handler starts. The verifier is injected so this module does not pay it, "
        "which moves the cost rather than removing it (D410)",
        "what a cite is verified *against*. 10:1970 says `the store`, and a session that touched "
        "four corpora has four; nothing says whether one unreachable corpus withholds its own "
        "cites or all of them. This module withholds per pair, which is the narrower reading",
        "whether the sweep belongs to every source or only the speaking ones. 10:1918 gives it to "
        "`SessionStart` without qualification, so it runs before the source check -- which means "
        "`startup`, the commonest session, is the one that does the housekeeping",
    )
