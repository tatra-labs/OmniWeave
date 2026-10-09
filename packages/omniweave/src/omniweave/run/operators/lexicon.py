"""`op.lexicon`: the corpus's names rebuilt after the drain, and the gazetteer re-opened. **D683.**

06-structure-extraction.md section 3.7 is the specification and `omniweave_core.store.lexicon` the
store half. A run's step, in order:

1. **build** -- `store.lexicon.build` in one read: the live corpus aliases, filtered;
2. **put** -- the artefact into the CAS, content-addressed, so an unchanged lexicon is one blob;
3. **point** -- `index_state.lexicon` to its digest, and in the same transaction enqueue a
   gazetteer row for every segmented unit without one (`DerivePlan.enqueue_readers`) and read the
   rows the move invalidates: every gazetteer row whose `dep` names another digest;
4. **re-open** -- those rows, through `converge.requeue` (a `free` row runs now).

The caller drains again when step 3 enqueued or step 4 re-opened anything.

## The timing, which is the one ruling here that departs from the plan's prose (D683)

06:1177 has `op.lexicon` run once per run after every document Pass, and the gazetteer in run *k*
read the lexicon built at the end of run *k-1*: a first ingest finds no names, a second finds them.
**This runs the re-opened rows in the same run instead.** The plan's order is kept -- the lexicon is
built after every document Pass, and the gazetteer reads the one built before it -- but the drain
that follows the build is this run's, not the next one's. One `ow ingest` therefore leaves the
graph converged, which is INV-18's question about a one-shot ingest, and the accessible direction
(one command, no second run to learn about). It is sound only because the gazetteer cannot move
the lexicon: it writes no alias, and its mentions are not counted (`store.lexicon` ruling 2), so a
second build after its drain finds the digest the first did. `test_run_gazetteer` builds again
after the drain and checks that nothing re-opens.

**Not a `work` row.** 08:619 gives the `op.*` steps `work` rows with a NULL routing triple; the
other one shipped, `op.converge`, is still library functions no run calls. A row here would need a
`unit` to name and would be claimed by the drain it must follow, so this is a step of the run, as
retirement is. Its cost is one read of `entity_alias` and one CAS write per run.
"""

from __future__ import annotations

import hashlib
import io
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Final, cast

from omniweave_core.store import lexicon
from omniweave_core.store import sqlite as ow

from omniweave.run.converge import requeue

if TYPE_CHECKING:
    from collections.abc import Mapping

    from omniweave_core.blobs import BlobStore

    from omniweave.run.operators.derive import DerivePlan

__all__ = ["OP_LEXICON", "LexiconReport", "empty_digest", "rebuild"]

OP_LEXICON: Final = "op.lexicon"
_EMPTY_DIGEST: Final = hashlib.sha256(lexicon.EMPTY).hexdigest()
"""What a row read before the first build (`empty_digest`): the CAS names a blob by its sha256."""


@dataclass(frozen=True, slots=True)
class LexiconReport:
    """One build, for `IngestReport`."""

    digest: str
    names: int
    candidates: int
    truncated: bool
    moved: bool
    """The digest differs from the one `index_state.lexicon` held before."""
    reopened: int
    """Gazetteer rows that read another lexicon, put back to `pending`."""
    enqueued: int = 0
    """Gazetteer rows written for segmented units that had none."""
    dropped: Mapping[str, int] = field(default_factory=dict)

    def line(self) -> str:
        why = ", ".join(f"{k} {v}" for k, v in self.dropped.items())
        return (
            f"  lexicon   {self.names} of {self.candidates} name(s)"
            + (f" (dropped: {why})" if why else "")
            + (", TRUNCATED at MAX_LEXICON_ENTRIES" if self.truncated else "")
            + (
                f"; moved, {self.reopened} gazetteer row(s) re-opened"
                if self.moved
                else "; unchanged"
            )
            + (f"; {self.enqueued} document(s) queued for the gazetteer" if self.enqueued else "")
        )

    @property
    def drain(self) -> bool:
        """Whether this build left gazetteer rows to run."""
        return bool(self.reopened or self.enqueued)


def empty_digest(cas: BlobStore) -> str:
    """The empty lexicon's digest, its artefact put in the CAS so a worker can open it."""
    return cas.put(io.BytesIO(lexicon.EMPTY)).hex()


def rebuild(
    thread: ow.StoreThread, cas: BlobStore, *, now_ms: int, derives: DerivePlan | None = None
) -> LexiconReport:
    """Steps 1-4. Returns what it did; the caller drains when `drain` says so.

    `derives` is `None` when no gazetteer resolved this run: the lexicon is still built and pointed
    at, so a later run that has one finds it, and nothing is enqueued.
    """
    built = cast(
        "lexicon.Built",
        thread.run(
            ow.Unit(
                name="lexicon.build", run=lexicon.build, cost_class="free", wait_ms=ow.BATCH_WAIT_MS
            )
        ),
    )
    digest = cas.put(io.BytesIO(built.body)).hex()

    def point(connection: Any) -> tuple[str | None, int, dict[int, str]]:
        prior = lexicon.current(connection)
        lexicon.set_current(connection, digest)
        enqueued = 0 if derives is None else derives.enqueue_readers(connection)
        return prior, enqueued, lexicon.stale(connection, digest)

    prior, enqueued, rows = cast(
        "tuple[str | None, int, dict[int, str]]",
        thread.run(
            ow.Unit(name="lexicon.point", run=point, cost_class="free", wait_ms=ow.BATCH_WAIT_MS)
        ),
    )
    reopened, _held = requeue(thread, rows, trigger="cli", now_ms=now_ms)
    return LexiconReport(
        digest=digest,
        names=built.names,
        candidates=built.candidates,
        truncated=built.truncated,
        moved=(prior or _EMPTY_DIGEST) != digest,
        reopened=reopened,
        enqueued=enqueued,
        dropped=built.dropped,
    )
