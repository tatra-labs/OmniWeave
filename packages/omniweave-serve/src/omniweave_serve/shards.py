"""Reading the shards an export sends: in order, at an offset, and across a roll. 15 section 8.4.

15:405 is the whole storage design in one clause: *"`ow trace tree`, `ow trace stat` and
`ow trace export` read shards **in place, streaming**; there is no index file, because a second
index is a second thing that can be wrong."* So a reader is a byte offset, an open handle and a
rule for what happens when the writer rotates underneath it.

## A POSITION IS A SHARD AND AN OFFSET, NOT AN OFFSET

15:256 calls the cursor *"the last shard offset it committed"*, which is a single number, and a
single number stops being a position the first time a run rolls. `{run}.0001.ndjson.gz` and
`{run}.ndjson` both have a byte 4,096. A cumulative offset across the sequence would be unique and
would move the moment `ow trace prune` unlinked a rolled shard — 15:399's retention does exactly
that on a fourteen-day cycle — so the only stable answer is the pair. D367.

`Position` is therefore `(shard, offset)` and the cursor holds both. A cursor written by an older
build, holding a bare integer, reads as *absent* under `read_cursor`'s existing tolerance rule: a
duplicate arrival is harmless and a wrong resume is not.

## WHAT AN OFFSET COUNTS

Uncompressed bytes into the shard's content, for both a live shard and a `.gz` archive of one.
That is the same quantity `shard.roll`'s `bytes` field carries (`NdjsonSink._written`), so a roll
record and a reader's offset are in the same units and can be compared. A compressed byte position
would be an implementation detail of the deflater and would change if the compression level ever
did.

## THE PARTIAL FINAL LINE, AND WHY THE OFFSET DOES NOT PASS IT

15:390: *"A partial final line is skipped on read, never repaired."* `parse_line` implements the
skipping; this module implements the *not advancing*. A writer holding an append handle can be
caught mid-record, and a follower that consumed the prefix and moved its offset past it would drop
that record permanently — the writer finishes the line a millisecond later and the follower is
already beyond it. So a trailing fragment with no newline is left unconsumed and the offset stops
in front of it, which makes the read idempotent at exactly the boundary that matters.

## THE ROLL, AND THE FIELD A FOLLOWER MUST ACTUALLY READ

15:273 says the `shard.roll` record carries *"the new shard's name"* and that the follower *"opens
the named successor"*. It does not. `NdjsonSink._roll` writes:

```python
fields={"closed": self._live.name,          # r_01.ndjson  <- the path that CONTINUES
        "successor": successor.name, ...}   # r_01.0001.ndjson.gz  <- the ARCHIVE of what closed
```

The rotation is copy-then-unlink, not rename: the closed bytes become the `.gz`, and the stream
continues at the same live path under a new inode. A follower that opened `successor` would open a
gzip file as text, on the line after the sentence forbidding exactly that — *"never re-reads a
`.gz`"*. `continues_at()` reads `closed`, and D362 is the entry.

## WHAT THIS MODULE DOES NOT HOLD

A clock, a loop and a sleep. `Tail.drain()` reads what is there **now** and returns; whether to
wait and drain again is the caller's, which is what keeps `--follow` testable as a sequence of
appends rather than as a race. `Tail` holds the open handle rather than the path for 15:272's
reason, and never stats in a loop.
"""

from __future__ import annotations

import gzip
import re
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Final, Protocol

from omniweave_core.errors import ConfigError
from omniweave_core.events import SHARD_ORDINAL_DIGITS, EventKind, parse_line

if TYPE_CHECKING:
    from collections.abc import Iterator

    from omniweave_core.events import Event

__all__ = [
    "GZ_SUFFIX",
    "LIVE_ORDINAL",
    "LIVE_SUFFIX",
    "Position",
    "Shard",
    "Tail",
    "continues_at",
    "read_shard",
    "shard_of",
    "shards_for",
    "walk",
]

LIVE_SUFFIX: Final = ".ndjson"
"""The live shard's extension. `[observe] ndjson_path` ends in it and `shard_path` strips it."""

GZ_SUFFIX: Final = ".ndjson.gz"
"""A rolled shard's. Deflated in the writer thread at roll time (15:398)."""

LIVE_ORDINAL: Final = 0
"""The live shard's ordinal. Rolls start at 1, which `shard_path` refuses to go below."""

_ROLLED: Final = re.compile(
    rf"^(?P<stem>.+)\.(?P<ordinal>\d{{{SHARD_ORDINAL_DIGITS}}})\.ndjson\.gz$"
)
"""`{stem}.NNNN.ndjson.gz`, with the digit count read off the constant that writes it."""


@dataclass(frozen=True, slots=True, order=True)
class Shard:
    """One file of a run's event stream, and where it sits in the order.

    `ordinal` sorts first, so sorting a set of ROLLED shards puts them in the order they rolled.
    The live shard is `LIVE_ORDINAL` and would sort before all of them, which is why `shards_for`
    appends it rather than sorting it in: it is the newest and it has no ordinal to say so.
    """

    ordinal: int
    path: Path

    @property
    def compressed(self) -> bool:
        """Whether reading it means inflating it. Every rolled shard; never the live one."""
        return self.path.name.endswith(GZ_SUFFIX)

    @property
    def name(self) -> str:
        """The file name, which is what a `Position` records: a cursor outlives a directory."""
        return self.path.name


@dataclass(frozen=True, slots=True)
class Position:
    """Where a reader stopped: which shard, and how many uncompressed bytes into it.

    A pair rather than 15:256's single *"shard offset"*, because one number stops identifying a
    place the first time a run rolls. D367.
    """

    shard: str
    offset: int

    def __post_init__(self) -> None:
        if self.offset < 0:
            raise ConfigError(
                f"a shard position of {self.offset}; an offset is a byte count",
                fix="delete .omniweave/events/.export_cursor.json and re-run the export",
            )


def shard_of(path: Path) -> Shard:
    """Classify one file. A name matching neither shape is `LIVE_ORDINAL`, like a live shard.

    Tolerant on purpose: `[observe] ndjson_path` is a template an operator may set to anything, so
    a name this module does not recognise is far more likely to be a legal configuration than a
    corruption, and refusing it would make an unusual path unreadable rather than unrolled.
    """
    match = _ROLLED.match(path.name)
    return Shard(ordinal=int(match.group("ordinal")) if match else LIVE_ORDINAL, path=path)


def shards_for(events_dir: Path, live: Path) -> tuple[Shard, ...]:
    """Every shard of one run, oldest first, with the live one last.

    `live` is the resolved `[observe] ndjson_path` for the run rather than a bare `run_id`, for
    `shard_path`'s reason: the template is the operator's and the rolled names sit beside whatever
    it produced. A missing directory is an empty tuple and not an error — a run that emitted
    nothing is a run with no shards, which `ow trace export` reports as zero spans.
    """
    stem = live.name.removesuffix(LIVE_SUFFIX)
    rolled: list[Shard] = []
    try:
        entries = sorted(events_dir.iterdir())
    except OSError:
        return ()
    for entry in entries:
        match = _ROLLED.match(entry.name)
        if match and match.group("stem") == stem:
            rolled.append(shard_of(entry))
    rolled.sort()
    return (*rolled, shard_of(live)) if live.is_file() else tuple(rolled)


class _Stream(Protocol):
    """The three things this module needs from a shard, and nothing else.

    Neither `BinaryIO` nor `IO[bytes]` covers both sides: `gzip.GzipFile` satisfies neither under a
    strict checker, and a `cast` to one of them would be asserting a shape rather than naming the
    one that is actually used. Iteration yields whole lines including the newline, which is what
    makes an offset a sum of line lengths.
    """

    def __iter__(self) -> Iterator[bytes]: ...

    def seek(self, offset: int, whence: int = 0, /) -> int: ...

    def close(self) -> None: ...


def _open(shard: Shard) -> _Stream:
    """One shard as a binary stream. Binary because an offset is a byte count, not a line count."""
    if shard.compressed:
        return gzip.open(shard.path, "rb")
    return shard.path.open("rb")


def read_shard(shard: Shard, *, start: int = 0) -> Iterator[tuple[Position, Event]]:
    """Every record from `start`, yielding the position AFTER each one.

    The position is the one to resume from, which is why it is the offset *after* the record: a
    cursor holding the position of a record already sent would re-send it on every resume, and
    re-sending forever is not the harmless duplicate 15:255 licenses.

    A line that `parse_line` refuses — a fragment, a blank, a document of another shape — advances
    the offset and yields nothing, because the bytes were consumed either way. A trailing fragment
    with no newline is the exception and is left where it is.
    """
    handle = _open(shard)
    try:
        if start:
            handle.seek(start)
        offset = start
        for raw in handle:
            if not raw.endswith(b"\n"):
                return
            offset += len(raw)
            event = parse_line(raw.decode("utf-8", errors="replace"))
            if event is not None:
                yield Position(shard=shard.name, offset=offset), event
    finally:
        handle.close()


def walk(
    shards: tuple[Shard, ...], *, resume: Position | None = None
) -> Iterator[tuple[Position, Event]]:
    """Every record of a run in order, starting after `resume`.

    A `resume` naming a shard that is no longer present -- `ow trace prune` unlinked it, which
    15:399 does on a fourteen-day cycle -- starts from the beginning of what remains. That
    re-sends and never skips, which is the direction 15:255 makes safe.
    """
    if resume is None:
        index = 0
    else:
        found = next((i for i, shard in enumerate(shards) if shard.name == resume.shard), None)
        if found is None:
            index = 0
        else:
            yield from read_shard(shards[found], start=resume.offset)
            index = found + 1
    for shard in shards[index:]:
        yield from read_shard(shard)


def continues_at(record: Event) -> str | None:
    """The shard name a follower opens after this `shard.roll`, or `None` for any other record.

    **`closed`, not `successor`**, and D362 is the entry. The rotation is copy-then-unlink: the
    bytes that were closed become `successor` (`{stem}.NNNN.ndjson.gz`) and the stream continues at
    `closed` (`{stem}.ndjson`) under a new inode. 15:273 says to open the successor and 15:274 says
    never to re-read a `.gz`; the two cannot both be followed, and this is the one that leaves a
    follower reading text.
    """
    if record.kind != EventKind.SHARD_ROLL.value:
        return None
    closed = record.fields.get("closed")
    return closed if isinstance(closed, str) and closed else None


class Tail:
    """A follower over the live shard: an open HANDLE, never a path. 15:271-274.

    *"The follower holds the open handle, not the path ... It never stats the path in a loop."*
    That is a correctness rule and not a performance one: the writer unlinks the live file at every
    roll, so a follower that reopened by path between two reads would race the unlink and read
    either nothing or a new file's first bytes as though they continued the old one.

    **`drain()` reads what is there now and returns.** Whether to wait and drain again belongs to
    the caller, which is what makes a roll testable as a sequence of appends rather than as a race,
    and what keeps this module free of a sleep.
    """

    __slots__ = ("_handle", "_offset", "_rolled", "_shard")

    def __init__(self, shard: Shard, *, start: int = 0) -> None:
        if shard.compressed:
            raise ConfigError(
                f"{shard.name} is a rolled shard; --follow tails the live one and 15:274 is "
                f"explicit that a follower never re-reads a .gz",
                fix="ow trace export --follow   # against the live shard, or drop --follow",
            )
        self._shard = shard
        self._handle: _Stream | None = shard.path.open("rb")
        self._handle.seek(start)
        self._offset = start
        self._rolled: str | None = None

    @property
    def position(self) -> Position:
        """Where this follower has consumed to."""
        return Position(shard=self._shard.name, offset=self._offset)

    @property
    def rolled(self) -> str | None:
        """The name to reopen once a `shard.roll` has been read, or `None` while following."""
        return self._rolled

    def drain(self) -> Iterator[tuple[Position, Event]]:
        """Every complete record available now. Stops at EOF, at a fragment, or at a roll.

        After a roll the handle is closed and `rolled` names the shard to open next; draining again
        yields nothing, so a caller that forgets to check cannot spin on a dead handle.
        """
        handle = self._handle
        if handle is None:
            return
        for raw in handle:
            if not raw.endswith(b"\n"):
                handle.seek(self._offset)
                return
            self._offset += len(raw)
            event = parse_line(raw.decode("utf-8", errors="replace"))
            if event is None:
                continue
            successor = continues_at(event)
            if successor is not None:
                self._rolled = successor
                self.close()
                return
            yield Position(shard=self._shard.name, offset=self._offset), event

    def close(self) -> None:
        """Release the handle. Idempotent, because a roll closes it and so does the caller."""
        handle, self._handle = self._handle, None
        if handle is not None:
            handle.close()

    def __enter__(self) -> Tail:
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()
