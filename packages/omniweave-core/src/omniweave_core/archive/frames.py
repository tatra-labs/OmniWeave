"""`Frame` -- the block-count-bounded run -- and `frames.json`, the archive's seek index.

Specified in 03-document-model.md section 13.3 (:2622-2634), whose record shape is printed
verbatim at 03-document-model.md:2483 as
`[{lo_page, lo_ord, hi_page, hi_ord, path, blocks, bytes, sha256}]`, and whose target of
**8,192 blocks** is set twice: 03-document-model.md:2485 and 16-roadmap.md:418.

**A Frame is bounded by BLOCK COUNT and deliberately not by page range** (03:2626-2630). One
page with 400,000 blocks -- a spreadsheet sheet rendered as one page -- makes page-ranged frames
non-uniform and forces a "frames may split within a page" exception that a second-language
reader gets wrong. Block-count bounding has no such case, which is why `lo_page`/`hi_page` are
*observations about* a frame rather than its definition.

**`(lo_page, lo_ord, hi_page, hi_ord)` is what makes the seek path real** (03:2631-2633): "give
me pages 300-320" is a binary search over this index followed by inflating two or three members,
and nothing else is read. `frames_overlapping()` below is that binary search; the ZIP central
directory supplies the offsets.

**A frame's `sha256` is over its UNCOMPRESSED NDJSON bytes** (03:2633), so a reader can verify a
member it inflated without re-deflating it -- which is the only verification a stdlib-only
reader can perform at all, since re-deflating would have to reproduce one zlib version's output.

**`Frame` is declared here and not in `omniweave_core.model`.** 03-document-model.md section
13.3 is its sole definition site and 16-roadmap.md:418 assigns it to W2.5 together with
`frames.json`; `Doc.frames() -> Iterator["Frame"]` (03:2597) is a *use* site in the model's lazy
read handle, which must import this name rather than redeclare it (INV-21). The name collision
the plan does warn about is a different one: the driver protocol's unit is also called a frame,
it lives in `omniweave_core.host.wire`, and its file is `wire.py` and never `frames.py`
(03-document-model.md:2636, charter.md section 5 X20) -- so this file name is legal precisely
because it is under `archive/` and not under `host/`.

Stdlib only (INV-2). No `sqlite3` (INV-17): an archive is a file, not a store.

Tier T-SCHEMA: 02-architecture.md section 2 row 25.
"""

from __future__ import annotations

import bisect
import itertools
import json
import re
from dataclasses import dataclass, fields
from typing import Any, Final

from omniweave_core.errors import ModelError

__all__ = [
    "BLOCKS_DIR",
    "FRAMES_MEMBER",
    "FRAME_TARGET_BLOCKS",
    "MARKS_DIR",
    "Frame",
    "frame_member",
    "frames_json",
    "frames_overlapping",
    "marks_member",
    "parse_frames_json",
]

FRAME_TARGET_BLOCKS: Final = 8_192
"""The target block count of one Frame. 03-document-model.md:2485 and 16-roadmap.md:418.

A **target**, not a ceiling, and therefore deliberately not in `omniweave_core.limits`: that
module carries numbers a producer is built never to exceed and names an overshoot-by-design
number `*_TARGET_*` instead (limits.py's own docstring, quoting charter.md section 6.10 on
`SEGMENT_TARGET_TOKENS`). The writer closes a frame once it holds this many blocks, so the last
frame is short and no frame is long.
"""

FRAMES_MEMBER: Final = "frames.json"
BLOCKS_DIR: Final = "blocks/"
MARKS_DIR: Final = "marks/"

_MEMBER_DIGITS: Final = 6
"""`blocks/000000.ndjson` -- six digits, from the member tree at 03-document-model.md:2485-2486.

Six digits hold 1,000,000 frames, which at 8,192 blocks each is 8.19e9 blocks: three orders of
magnitude above `MAX_BLOCKS_PER_DOC` (8,388,608, i.e. 1,024 frames), so the width can never be
the thing that fails.
"""

_SHA256_HEX: Final = re.compile(r"^[0-9a-f]{64}$")

_FIX = "ow doc export --recompute-frames"
"""One `fix` for every refusal in this module: the frame index is a derived artefact.

`OwError.__init__` refuses an empty `fix` (errors.py), and every failure here means the index
does not describe the members, which re-exporting is exactly what repairs.
"""


@dataclass(frozen=True, slots=True)
class Frame:
    """One `frames.json` record, field for field with 03-document-model.md:2483.

    The four coordinates are INCLUSIVE bounds over the blocks actually in the member -- the
    first record's `(page, ord)` and the last record's -- because a frame boundary falls
    wherever the block count ran out and there is no half-open interval to name. `blocks` and
    `bytes` count the member's NDJSON lines and its uncompressed bytes; `sha256` is over those
    same uncompressed bytes (03:2633).
    """

    lo_page: int
    lo_ord: int
    hi_page: int
    hi_ord: int
    path: str
    blocks: int
    bytes: int
    sha256: str

    def __post_init__(self) -> None:
        for name in ("lo_page", "lo_ord", "hi_page", "hi_ord", "blocks", "bytes"):
            value = getattr(self, name)
            if not isinstance(value, int) or isinstance(value, bool) or value < 0:
                msg = f"Frame.{name} is a non-negative int, got {value!r}"
                raise ModelError(msg, fix=_FIX)
        if (self.lo_page, self.lo_ord) > (self.hi_page, self.hi_ord):
            msg = (
                f"Frame {self.path} has lo ({self.lo_page}, {self.lo_ord}) above "
                f"hi ({self.hi_page}, {self.hi_ord}); frames.json is in (page, ord) order"
            )
            raise ModelError(msg, fix=_FIX)
        if self.blocks == 0:
            msg = f"Frame {self.path} claims zero blocks; an empty member is never written"
            raise ModelError(msg, fix=_FIX)
        if not _SHA256_HEX.match(self.sha256):
            msg = f"Frame.sha256 is 64 lowercase hex chars, got {self.sha256!r}"
            raise ModelError(msg, fix=_FIX)

    def as_record(self) -> dict[str, Any]:
        """The JSON object, keys in 03-document-model.md:2483's printed order.

        Key ORDER is load-bearing rather than cosmetic: `frames.json` goes into a byte-stable
        archive (INV-10), so the writer may not depend on a dict-insertion accident. It is
        written out once here and `frames_json()` does not re-sort it.
        """
        return {
            "lo_page": self.lo_page,
            "lo_ord": self.lo_ord,
            "hi_page": self.hi_page,
            "hi_ord": self.hi_ord,
            "path": self.path,
            "blocks": self.blocks,
            "bytes": self.bytes,
            "sha256": self.sha256,
        }


def frame_member(index: int) -> str:
    """`blocks/000063.ndjson` for index 63 -- the spelling 03-document-model.md:2504 greps for."""
    return f"{BLOCKS_DIR}{index:0{_MEMBER_DIGITS}d}.ndjson"


def marks_member(index: int) -> str:
    """`marks/000063.ndjson` -- the marks member of the SAME frame index.

    Frame-aligned on purpose: the marks of the blocks in `blocks/000063.ndjson` are exactly the
    records of `marks/000063.ndjson`, so a reader that seeks to a page range inflates the marks
    it needs and no others. 03-document-model.md:2486 lists `marks/000000.ndjson` in the member
    tree without saying what indexes it, and aligning it with the block frames is the only
    choice under which section 13.3's seek path also covers marks.
    """
    return f"{MARKS_DIR}{index:0{_MEMBER_DIGITS}d}.ndjson"


def frames_json(frames: tuple[Frame, ...]) -> bytes:
    """`frames.json`'s exact bytes: a pretty-printed array, LF-terminated, no trailing spaces.

    Pretty-printed for the reason `manifest.json` is (03:2485): `jq` and `unzip -p` are the
    documented reading tools and a one-line 1,221-element array is readable by neither.
    `separators` is passed explicitly because `json.dumps`'s default item separator is `", "`,
    which under `indent` leaves a trailing space before every newline -- the classic source of a
    diff git shows and a human cannot see.
    """
    body = json.dumps(
        [frame.as_record() for frame in frames],
        indent=2,
        separators=(",", ": "),
        ensure_ascii=False,
        allow_nan=False,
    )
    return (body + "\n").encode("utf-8")


def parse_frames_json(raw: bytes) -> tuple[Frame, ...]:
    """Decode `frames.json`, refusing a shape that would make the seek path silently wrong.

    Unlike every other non-manifest member, a malformed `frames.json` is NOT tolerated into
    `status = partial`: the tolerance rule at 03-document-model.md:2516 exists so a missing
    optional member degrades a read, and a frame index that does not describe the frames is not
    a degradation but a reader returning the wrong blocks for a page range. A caller that wants
    tolerance falls back to reading every `blocks/*.ndjson` member in name order, which is what
    `OwdocReader` does when the member is absent altogether.
    """
    try:
        parsed = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        msg = f"{FRAMES_MEMBER} is not UTF-8 JSON: {exc}"
        raise ModelError(msg, fix=_FIX) from exc
    if not isinstance(parsed, list):
        msg = f"{FRAMES_MEMBER} is an ARRAY of frame records (03:2483), got {type(parsed).__name__}"
        raise ModelError(msg, fix=_FIX)
    frames = tuple(_frame(entry, at=index) for index, entry in enumerate(parsed))
    _check_monotonic(frames)
    return frames


def _frame(entry: object, *, at: int) -> Frame:
    if not isinstance(entry, dict):
        msg = f"{FRAMES_MEMBER}[{at}] is an object, got {type(entry).__name__}"
        raise ModelError(msg, fix=_FIX)
    missing = sorted({f.name for f in fields(Frame)} - set(entry))
    if missing:
        msg = f"{FRAMES_MEMBER}[{at}] is missing {', '.join(missing)} (03:2483 prints all eight)"
        raise ModelError(msg, fix=_FIX)
    return Frame(
        lo_page=entry["lo_page"],
        lo_ord=entry["lo_ord"],
        hi_page=entry["hi_page"],
        hi_ord=entry["hi_ord"],
        path=str(entry["path"]),
        blocks=entry["blocks"],
        bytes=entry["bytes"],
        sha256=str(entry["sha256"]),
    )


def _check_monotonic(frames: tuple[Frame, ...]) -> None:
    """The index is sorted and non-overlapping, which is what licenses the binary search.

    `frames_overlapping()` bisects on `hi_page`; a bisect over an unsorted sequence returns a
    plausible wrong answer rather than an error, so the property is asserted once at parse time
    instead of being assumed at every call.
    """
    for previous, current in itertools.pairwise(frames):
        if (previous.hi_page, previous.hi_ord) >= (current.lo_page, current.lo_ord):
            msg = (
                f"{FRAMES_MEMBER} frames {previous.path} and {current.path} overlap or are out "
                f"of order: {(previous.hi_page, previous.hi_ord)} then "
                f"{(current.lo_page, current.lo_ord)}"
            )
            raise ModelError(msg, fix=_FIX)


def frames_overlapping(frames: tuple[Frame, ...], pages: range) -> tuple[Frame, ...]:
    """The frames that can hold a block on a page in `pages`. THE SEEK PATH (03:2631).

    A binary search and not a scan, because 03-document-model.md:2604 prices the alternative:
    reading pages 300-320 of a 5,000-page archive must inflate two or three members, and a
    linear walk of a 1,221-entry index to *decide* which two is free while a linear walk of the
    MEMBERS is 750 MB. The bisect runs on `hi_page`, which `_check_monotonic` has proved
    non-decreasing.

    `pages.step` must be 1: a frame's coordinates bound a contiguous run, so a strided range
    would need per-page containment, which the index cannot answer. Refusing is the only
    alternative to answering it wrong.

    Returns the frames in index order, so a caller inflating them in sequence reads the archive
    forward.
    """
    if pages.step != 1:
        msg = f"frames_overlapping takes a contiguous page range, got step {pages.step}"
        raise ModelError(msg, fix="ow doc read --pages LO-HI")
    if not frames or len(pages) == 0:
        return ()
    first = bisect.bisect_left(frames, pages.start, key=lambda f: f.hi_page)
    return tuple(f for f in frames[first:] if f.lo_page < pages.stop)
