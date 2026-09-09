"""The `.owdoc` codec: the twenty-nine wire keys, the byte-stable writer, the seeking reader.

Specified in 03-document-model.md section 13.2 (the member tree at :2480-2521), section 3.1 (the
frozen wire-key table at :645-679), section 3.2 (the generated JSON Schema, whose `required`
list at :679 is the authority on which keys a record may omit) and section 13.3 (the Frame).
`export(store, path)` and `import_(path, sink)` are named as this subpackage's two entry points
by 02-architecture.md:249.

**A plain ZIP with `ZIP_DEFLATED` members, and no zstd anywhere on the read path** (03:2497).
The reason is not compression ratio: `compression.zstd` is Python 3.14+, which would put zstd
across the whole floor for a 10-15% archive-size win, and `unzip -p x.owdoc
blocks/000063.ndjson | jq` must need no external decompressor. 16-roadmap.md:418 makes that "a
test, not a claim", and `test_archive_owdoc.py` is where the claim is cashed.

**The archive never contains a `block_id`** (03:2508, :1083). Every internal reference -- parent,
`rel` endpoints, grid origins, mark owners, asset links -- is an `addr`, and import assigns fresh
`block_id`s. That is what makes an archive portable between stores and what makes the
export-diff gate (G28, not G6 -- ADR-2 decision 4) sound.

**`pa` is COMPUTED from `i`, and never read from a store.** `addr`'s grammar (03:1091-1105) makes
a block's parent its own address minus the last step, with the one-step case naming the page root
whose parent is the literal `doc`. So the writer needs no `block_id -> addr` map and no ordering
guarantee between a parent and its children, which matters because `ord` is sibling-local: a
parent does not reliably precede its child in the `(page, ord)` order a Frame is written in
(03:2624).

**Byte stability, and how `zipfile`'s default mtime was defeated.** INV-10 is byte-exactness and
03:2505 makes the deep-golden `rebind()` diff "a diff of two files", so two exports of one
generation must be one file twice. `zipfile.ZipInfo(name)` stamps `time.localtime()` into
`date_time` and picks `create_system` from `sys.platform` (0 on Windows, 3 elsewhere), so the
default constructor alone makes an archive differ between two runs on one machine AND between
two machines on one run. `_member_info()` therefore builds every `ZipInfo` by hand: `date_time`
is the DOS epoch `(1980, 1, 1, 0, 0, 0)` -- the earliest a ZIP date field can express, so it is
a constant and not a clamp -- `create_system` is pinned to 3, `external_attr` to `0o644 << 16`,
and `compress_type` to `ZIP_DEFLATED` on every member including the ones that would compress
worse than stored. Member order is fixed by the writer's own single pass and never by a
directory listing. What is left outside omniweave's control is zlib's deflate output for a given
level, which is stable for a zlib version and not guaranteed across versions; the
version-independent identity is therefore `frames.json`'s per-frame `sha256`, taken over the
UNCOMPRESSED NDJSON (03:2633), which is exactly why the plan puts the digest there.

**Reading is bounded, because an archive is untrusted input** (14-security.md section 2.2). Every
read goes through `_Package.read()`, which is that section's five-step algorithm transcribed: a
central-directory pre-filter on `uncompressed_size(name)`, a cache whose hits are free and
uncharged, a `cap+1` read against `min(MAX_ENTRY_BYTES, remaining)`, and an error naming the
**binding** budget rather than whichever check ran last. `extractall` is never called and is
semgrep-banned framework-wide (14:266).

Stdlib only (INV-2). No `sqlite3` (INV-17): `export` takes a read protocol, not a connection.

Tier T-SCHEMA: 02-architecture.md section 2 row 25.
"""

from __future__ import annotations

import hashlib
import io
import json
import zipfile
from collections.abc import Iterable, Iterator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from types import MappingProxyType
from typing import IO, Any, Final, Protocol

from omniweave_core.archive.frames import (
    BLOCKS_DIR,
    FRAME_TARGET_BLOCKS,
    FRAMES_MEMBER,
    MARKS_DIR,
    Frame,
    frame_member,
    frames_json,
    frames_overlapping,
    marks_member,
    parse_frames_json,
)
from omniweave_core.archive.manifest import (
    MANIFEST_MEMBER,
    Manifest,
    manifest_json,
    parse_manifest,
    require_readable,
)
from omniweave_core.errors import ModelError, PolicyRefusal, ResourceLimit
from omniweave_core.limits import MAX_CONTAINER_TOTAL_BYTES, MAX_ENTRY_BYTES, effective
from omniweave_core.model import (
    Addr,
    Block,
    BlockDraft,
    CellPos,
    Cite,
    Kind,
    Layer,
    Mark,
    Method,
    OriginBytes,
    OriginGlyphs,
    OriginNodePath,
    OriginNone,
    OriginPixels,
    OriginSpan,
    Quad,
    Quote,
    RelKind,
    TextSpan,
    Trust,
)

__all__ = [
    "ASSETS_DIR",
    "DIAGS_MEMBER",
    "GRIDS_MEMBER",
    "PARTS_DIR",
    "RELS_MEMBER",
    "REQUIRED_KEYS",
    "TOC_MEMBER",
    "VIEWS_DIR",
    "WIRE_KEYS",
    "AssetRow",
    "BlockExport",
    "BlockImport",
    "DocHeader",
    "ExportSource",
    "GridRow",
    "OwdocReader",
    "PartRow",
    "RelRow",
    "ViewRow",
    "block_record",
    "export",
    "import_",
    "member_name_ok",
    "parent_addr",
    "read_block_record",
]

# ---------------------------------------------------------------------------
# 1. The member vocabulary. 03-document-model.md:2480-2492's printed tree.
# ---------------------------------------------------------------------------

RELS_MEMBER: Final = "rels.ndjson"
GRIDS_MEMBER: Final = "grids.ndjson"
DIAGS_MEMBER: Final = "diags.json"
TOC_MEMBER: Final = "toc.json"
PARTS_DIR: Final = "parts/"
ASSETS_DIR: Final = "assets/cas/"
VIEWS_DIR: Final = "views/"

WIRE_KEYS: Final = (
    "i", "c", "p", "pa", "o", "k", "rk", "ly", "lb", "t", "ts", "os", "q", "m",
    "qt", "tr", "mt", "sc", "pd", "oo", "od", "cd", "ld", "rm", "rb", "st", "dc", "pl", "x",
)  # fmt: skip
"""The twenty-nine keys of 03-document-model.md section 3.1, in the table's printed row order.

Charter D2 froze twenty-two at charter.md:1597; erratum E52 supersedes that set with this table
and appends `c`, `qt`, `mt`, `lb`, `pl`, `st` and `dc` -- twenty-nine at `model_version = "1.1"`
(03:686-693). Order matters here for one reason only: a record is serialised in this order, so
the archive's bytes do not depend on a dict-insertion accident (INV-10).

`tools/wirekeys.toml` is named at 03:648 as the register CI diffs, and it does not yet exist in
the tree; this tuple is the only place the twenty-nine are written down. Reported.
"""

REQUIRED_KEYS: Final = frozenset(
    {
        "i",
        "c",
        "p",
        "pa",
        "o",
        "k",
        "ly",
        "t",
        "os",
        "qt",
        "tr",
        "mt",
        "pd",
        "oo",
        "od",
        "cd",
        "rm",
        "rb",
        "st",
    }
)
"""The nineteen keys 03-document-model.md:679's generated JSON Schema marks `required`.

The ten that are NOT required are `rk`, `lb`, `ts`, `q`, `m`, `sc`, `ld`, `dc`, `pl` and `x`.
`m`'s absence from this set is load-bearing: it is what makes a separate `marks/NNNNNN.ndjson`
member coherent beside a frozen `m` key -- see `_MARKS_ARE_A_MEMBER` below.
"""

_MARKS_ARE_A_MEMBER: Final = """03-document-model.md defines marks twice and the two readings
are reconciled rather than chosen between. :2486 lists `marks/000000.ndjson` in the member tree;
:659 freezes `m` as a wire key whose shape :700 fixes as an array of `[a, b, kind, value]`. A
writer that did both would put every mark in the archive twice, and a digest taken over one copy
would not cover the other.

The reconciliation is that `m` is absent from :679's `required` list. So the block record omits
`m`, and `marks/NNNNNN.ndjson` carries records `{"i": <addr>, "m": [[a, b, kind, value], ...]}`
using the frozen key with exactly its frozen meaning and shape. Both definition sites stay true,
one copy exists, and the marks member is frame-aligned so the seek path of section 13.3 reaches
marks as well as blocks -- which is also what section 2.7's 512-block mark window needs.

The reader accepts an inline `m` on a block record if it finds one, because 03:2720 makes
backward compatibility within a MAJOR unconditional and a future writer may legally choose the
inline form."""

# ---------------------------------------------------------------------------
# 2. Deterministic ZIP mechanics.
# ---------------------------------------------------------------------------

_ZIP_EPOCH: Final = (1980, 1, 1, 0, 0, 0)
"""The earliest instant a ZIP DOS date field can express, so it is a constant, not a clamp.

`zipfile` raises for a year below 1980, and every reproducible-ZIP toolchain in the world picks
this instant for that reason. An archive carries no timestamp of its own: the facts about when a
generation was made live in `doc`, `producer` and the run manifest, where they are queryable.
"""

_CREATE_SYSTEM: Final = 3
"""Unix, pinned. `ZipInfo.__init__` picks 0 on Windows and 3 elsewhere.

Leaving it at the default makes the same input produce different bytes on two machines, which is
the half of INV-10's byte-exactness that a same-machine re-export test cannot catch.
"""

_MEMBER_MODE: Final = 0o644 << 16
"""`external_attr`: rw-r--r--, pinned for the same cross-machine reason as `_CREATE_SYSTEM`."""

_COMPRESSLEVEL: Final = 9
"""Pinned so the deflate stream does not move with zlib's default.

zlib's default level is 6 and `zipfile` passes `None` through to it, so an unpinned level makes
the bytes depend on the zlib build. Level 9 is the ratio the archive-size arithmetic at 03:2652
(~75 B/block deflated) is measured against.
"""

_ATOMIC_SUFFIX: Final = ".owdoc-part"
"""A half-written archive is never left under the caller's name.

The write goes to a sibling and `Path.replace` (which is `os.replace`, atomic on POSIX and on
Windows for a same-directory rename) puts it in place, so a crash mid-export leaves the previous
archive intact rather than a truncated ZIP with no central directory.
"""


def _member_info(name: str, size_hint: int = 0) -> zipfile.ZipInfo:
    """A `ZipInfo` with every platform- and clock-dependent field pinned. See the module docstring.

    `size_hint` is advisory only -- `writestr` recomputes `file_size` from the data it is given.
    It exists so a caller can be explicit that a member is written from memory.
    """
    info = zipfile.ZipInfo(filename=name, date_time=_ZIP_EPOCH)
    info.compress_type = zipfile.ZIP_DEFLATED
    info.create_system = _CREATE_SYSTEM
    info.external_attr = _MEMBER_MODE
    info.file_size = size_hint
    return info


# ---------------------------------------------------------------------------
# 3. Member names: a NAME-SHAPE gate, and deliberately not a second `confine()`.
# ---------------------------------------------------------------------------

_WINDOWS_DEVICES: Final = frozenset(
    {
        "con",
        "prn",
        "aux",
        "nul",
        *(f"com{n}" for n in range(1, 10)),
        *(f"lpt{n}" for n in range(1, 10)),
    }
)
_MAX_COMPONENT_BYTES: Final = 255
_MAX_MEMBER_DEPTH: Final = 8
"""The deepest legal member is `assets/cas/ab/cd/<sha>.png` at five components.

Eight leaves room for a part path of three components under `parts/` and refuses a member whose
only purpose is to be deep.
"""


def member_name_ok(name: str) -> bool:
    """Is `name` a legal `.owdoc` member name? A pure predicate over the NAME, no filesystem.

    **This is not a second `confine()` and could not be one.** `confine()`
    (14-security.md:275-296) resolves a candidate against an EXISTING base directory, collapses
    `..` and follows symlinks in that order, and lives in `omniweave_core.paths` -- a module
    that does not yet exist in the tree. It cannot do this job: `OwdocReader` never writes a
    member to disk, it reads members by name out of the ZIP central directory, so there is no
    base to resolve against and no descriptor to re-`fstat`. What is needed here is the check
    14-security.md:1251 calls for on omniweave's own data artefacts -- the bounded reader "with
    `confine()` on every member" -- reduced to the half that applies when nothing is extracted.
    The exploded `.owdoc.d/` form (03:2521) DOES write files and IS `confine()`'s caller; that
    path is owed to whoever lands `omniweave_core.paths`. Reported.

    Refuses, tracking `confine()`'s refusal list clause for clause where the clause is about the
    name: an absolute or drive-relative member, any `.` or `..` segment, an empty segment, a
    backslash (ZIP separators are `/`; a Windows reader would treat `a\\b` as a directory), a
    trailing dot or space, a Windows reserved device name with or without an extension, an
    alternate data stream (`report.docx:evil`), a component above 255 bytes, and a NUL.

    `../../evil` is refused by the `..` clause, which is the zip-slip row of 14-security.md
    section 10 and the fixture `test_archive_owdoc.py` writes.
    """
    if not name or "\x00" in name or "\\" in name:
        return False
    if name.startswith("/") or (len(name) > 1 and name[1] == ":"):
        return False
    components = name.split("/")
    if len(components) > _MAX_MEMBER_DEPTH:
        return False
    return all(_component_ok(component) for component in components)


def _component_ok(component: str) -> bool:
    if not component or component in {".", ".."} or ":" in component:
        return False
    if component != component.rstrip(". "):
        return False
    if len(component.encode("utf-8")) > _MAX_COMPONENT_BYTES:
        return False
    return component.split(".", 1)[0].lower() not in _WINDOWS_DEVICES


def _require_member_name(name: str) -> None:
    if not member_name_ok(name):
        msg = (
            f"archive member {name!r} is not a legal member name: an .owdoc is read by name "
            f"through a validated map and never extracted (14-security.md:266). This is "
            f"zip-slip or a forged archive"
        )
        raise PolicyRefusal(msg, symbol="OW_PATH_OUTSIDE_ROOTS", fix="ow doc verify <archive>")


# ---------------------------------------------------------------------------
# 4. `addr` arithmetic. 03-document-model.md section 6.2.
# ---------------------------------------------------------------------------

ROOT_ADDR: Final = Addr("doc")
"""The `document` root's address is the literal `doc` (03:1093). It is the one block with no
parent, and the one whose page is meaningless because it spans every page."""


def parent_addr(addr: str) -> Addr | None:
    """The parent's `addr`, derived from the child's. `None` only for `doc` (03:1093).

    Three cases, and they are the three rules of 03-document-model.md section 6.2:

    * `doc` has no parent -- it is the one block with `parent_id IS NULL`;
    * a one-step address such as `p14/3` is a PAGE ROOT, whose parent is the `document` root;
    * every deeper address drops its last step, whether that step is an `ord` or a `r<r>c<c>`
      cell reference.

    Deriving rather than storing is what lets the writer emit blocks in `(page, ord)` order
    without a `block_id -> addr` map: `ord` is sibling-local (03:1113), so a parent does not
    reliably precede its children, and a map over a 600k-block generation is exactly the
    residency the archive path is built to avoid (03:2604).
    """
    if addr == ROOT_ADDR:
        return None
    head, sep, _ = addr.rpartition("/")
    if not sep:
        msg = f"addr {addr!r} has no step separator and is not the literal 'doc' (03:1091)"
        raise ModelError(msg, fix="ow doc verify <doc>")
    return Addr(head) if "/" in head else ROOT_ADDR


def _addr_depth(addr: str) -> int:
    """Step count. `doc` is 0, `p14/3` is 1, `p14/3/r2c5/0` is 3."""
    return 0 if addr == ROOT_ADDR else addr.count("/")


# ---------------------------------------------------------------------------
# 5. The row types the archive moves, and the two protocols at its edges.
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class DocHeader:
    """Everything `manifest.json` needs about the document, minus the counts the writer derives.

    **This is not `DocRecord`.** `DocSink.begin_doc(rec: DocRecord)` (03:548) takes
    `omniweave_core.model`'s record, which is not yet declared in the tree; `DocHeader` is the
    manifest's projection of the same `doc` row and carries every field the manifest key set at
    03:2482-2484 names. `import_` passes it to `begin_doc` through a caller-supplied factory so
    that the day `DocRecord` lands, the change is one default in this module and no call site.
    Reported.
    """

    doc_key: str
    gen: int
    status: str
    source: Mapping[str, Any]
    declared: Mapping[str, Any]
    achieved: Mapping[str, Any]
    producers: Sequence[Mapping[str, Any]] = ()
    confidence: Mapping[str, Any] = field(default_factory=dict)
    timings_ms: Mapping[str, Any] = field(default_factory=dict)
    x: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class BlockExport:
    """One block on its way out: the `Block` plus the two facts `Block` deliberately does not hold.

    `payload` and `decision_id` are the two `block` columns 03:311 leaves off `Block` because
    neither is meaningful without a join, and they are wire keys `pl` and `dc`. They therefore
    reach the codec beside the block rather than on it. `producer` is the index into
    `manifest.producers[]` that wire key `pd` holds (03:666) -- an INDEX and not a
    `producer_id`, for the same reason the archive holds no `block_id`.
    """

    block: Block
    producer: int
    payload: Mapping[str, Any] | None = None
    decision_id: str | None = None


@dataclass(frozen=True, slots=True)
class BlockImport:
    """One block on its way in: a `BlockDraft` plus every field the host would otherwise mint.

    `addr`, `cite`, `page` and `ord` are not `BlockDraft` fields -- the host mints them at
    `add_block` (03:65) -- but an archive carries all four, and `cite` in particular CANNOT be
    re-minted: it is durable across generations and `doc.next_cite_n` never reuses a number,
    which is the whole reason `c` had to become a wire key (03:687). `import_` hands them to
    the sink through `BlockDraft.x` under the reserved `x.ow.` vendor segment; see `import_`.
    """

    addr: Addr
    cite: Cite
    page: int
    ord: int
    parent: Addr | None
    draft: BlockDraft
    producer: int
    content_digest: bytes
    revision: int
    restriction_bits: int
    tombstoned: bool
    origin_operator: str
    origin_driver: str
    driver_schema_v: int
    layout_digest: bytes | None = None
    decision_id: str | None = None


@dataclass(frozen=True, slots=True)
class RelRow:
    """One `rel` row with `addr` endpoints. The store's `0001_init.sql` `CREATE TABLE rel`.

    `src_id`/`dst_id` become `src`/`dst` addresses, because the archive holds no `block_id`
    (03:2508). `producer` is a `manifest.producers[]` index, as on a block.
    """

    src: Addr
    dst: Addr
    kind: RelKind
    producer: int
    trust: Trust
    origin_operator: str
    score: float | None = None
    score_kind: str | None = None
    x: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class GridRow:
    """One `table_meta` row plus its origin `cell` geometry, addressed by `addr`.

    `grid_slot` is deliberately absent: 03:2467 classifies it `[DER]`, rebuildable by
    `ow store rebuild`, and explicitly outside the read contract. Exporting a derived cover map
    would put a second, staler truth in the archive; the map is a pure function of `cells` plus
    `n_rows`/`n_cols`, which is also what lets `owcheck`'s grid clause run against an archive.

    `cells` carries `(r, c, row_span, col_span)` per ORIGIN cell. The cell's own address is
    `f"{table}/r{r}c{c}"` by 03:1105's rule, so it is not stored twice.
    """

    table: Addr
    n_rows: int
    n_cols: int
    row_len: tuple[int, ...]
    kind: str
    cells: tuple[tuple[int, int, int, int], ...]
    header_rows: int = 0
    header_cols: int = 0
    recon_strategy: str | None = None
    recon_score: float | None = None
    has_merges: bool = False
    native_part: str | None = None
    native_sha256: str | None = None


@dataclass(frozen=True, slots=True)
class PartRow:
    """One `part` row. `store_ref` becomes `present`, because a member either exists or does not.

    `present = False` is 03:2488's "OPTIONAL (present:false)": the path, `sha256` and `byte_len`
    travel even when the bytes did not, which is what `[store] retain_parts` decides and what
    lets INV-10's `glyphs` branch name WHICH part it could not read (03:604-608).
    """

    path: str
    sha256: str
    byte_len: int
    present: bool = False


@dataclass(frozen=True, slots=True)
class AssetRow:
    """One `asset` row.

    Content-addressed, separately deletable and separately storable (03:2489).
    """

    sha256: str
    media_type: str
    byte_len: int
    present: bool = False
    origin_part: str | None = None
    width: int | None = None
    height: int | None = None
    licence: str | None = None
    spdx: str | None = None
    source_url: str | None = None
    restriction_bits: int = 0
    roles: tuple[tuple[Addr, str], ...] = ()


@dataclass(frozen=True, slots=True)
class ViewRow:
    """One serialized view: `views/md-1-7c3f.md` plus its sha256 and byte length (03:2490)."""

    view_id: str
    sha256: str
    byte_len: int
    text: str = ""


class ExportSource(Protocol):
    """The smallest read protocol `export()` needs. Nine methods, none of them a store handle.

    **Deliberately neither `Store` nor `Reader`.** Both are frozen at the end of P2
    (16-roadmap.md:428) and neither carries per-document row access: `Store` is the four-method
    QUEUE boundary and `Reader` is the six-method RETRIEVAL boundary
    (07-store-and-retrieval.md:56-70). Widening either to serve an exporter is exactly what
    "never widened" forbids. The type that DOES have this shape is `Doc`, the lazy read handle
    of 03-document-model.md:2584-2606, whose `blocks()`, `rels()`, `grid()` and `frames()` are
    the same reads under different names; when `Doc` lands it satisfies this protocol
    structurally and `export(doc, path)` is the call.

    `blocks()` yields in `(page, ord)` order, which is a Frame's order by definition (03:2624).
    Every other method may yield in any order: the writer sorts what must be sorted and the
    members that are not frames have no ordering law.
    """

    def header(self) -> DocHeader: ...
    def blocks(self) -> Iterable[BlockExport]: ...
    def rels(self) -> Iterable[RelRow]: ...
    def grids(self) -> Iterable[GridRow]: ...
    def parts(self) -> Iterable[tuple[PartRow, bytes]]: ...
    def assets(self) -> Iterable[tuple[AssetRow, bytes]]: ...
    def views(self) -> Iterable[ViewRow]: ...
    def diags(self) -> Iterable[Mapping[str, Any]]: ...
    def toc(self) -> Sequence[Mapping[str, Any]]: ...


# ---------------------------------------------------------------------------
# 6. The record codec. 03-document-model.md sections 3.1 and 3.2.
# ---------------------------------------------------------------------------

_ORIGIN_ENCODERS: Final = MappingProxyType(
    {
        OriginBytes: lambda o: {
            "k": "bytes",
            "part": o.part,
            "a": o.start,
            "len": o.length,
            "codec": o.codec,
        },
        OriginNodePath: lambda o: {"k": "nodepath", "part": o.part, "path": list(o.path)},
        OriginGlyphs: lambda o: {
            "k": "glyphs",
            "part": o.part,
            "extractor": o.extractor,
            "a": o.start,
            "len": o.length,
        },
        OriginPixels: lambda o: {"k": o.os_kind.value},
        OriginNone: lambda o: {"k": o.os_kind.value},
    }
)
"""`os`, per variant. **An offset pair is `(a, len)` and never `(a, b)`** (03:671-675).

The `bytes` and `glyphs` variants carry a start and a LENGTH because that is what the charter's
`os_a`/`os_b` columns hold; `ts` carries a half-open RANGE. Two different quantities never share
a letter, and reusing `b` for a length in one object and an end offset in another is the exact
class of bug 03:674 says costs a week. `spans.py` spells the same distinction as `start`/`length`
against `TextSpan.a`/`.b`, so the two encodings agree by construction.

**`pixels` carries neither a page nor a quad, and that is not an omission** (03:779-783). The
polygon IS the address and the polygon is already `q`; the page is already `p`. Emitting them
twice would create two facts that can disagree, and the store has nowhere to put a second quad.
"""


def block_record(export_row: BlockExport) -> dict[str, Any]:
    """One block as its wire record: the twenty-nine keys, in `WIRE_KEYS` order.

    Keys are emitted in the frozen table's order rather than sorted, so a record's bytes are a
    function of the block and nothing else (INV-10). Absent optional values are written as
    `null` rather than omitted, because 03:2722's backward-compatibility rule reads an ABSENT
    field as its documented default and counts the absence -- writing `null` for a genuinely
    null value keeps "absent" available to mean "this writer predates the key".

    The two reserved keys `x.ow.cite` and `x.ow.addr` are stripped from `x` on the way out.
    `import_` puts them there to carry an archive's durable `cite` through
    `DocSink.add_block`'s frozen signature; a store that persisted them would export a block
    whose `x` re-states its own identity, and `x` is not a digest input so nothing detects it.
    """
    block = export_row.block
    origin = _ORIGIN_ENCODERS[type(block.origin)](block.origin)
    record = {
        "i": str(block.addr),
        "c": str(block.cite),
        "p": block.page,
        "pa": _as_str_or_none(parent_addr(str(block.addr))),
        "o": block.ord,
        "k": block.kind.value,
        "rk": block.raw_kind,
        "ly": block.layer.value,
        "lb": block.label,
        "t": block.text,
        "ts": None if block.span is None else [block.span.a, block.span.b],
        "os": origin,
        "q": None if block.quad is None else list(block.quad),
        "qt": block.quote.name.lower(),
        "tr": block.trust.name.lower(),
        "mt": block.method.value,
        "sc": None if block.score is None else [block.score, block.score_kind],
        "pd": export_row.producer,
        "oo": block.origin_operator,
        "od": [block.origin_driver, block.driver_schema_v],
        "cd": block.content_digest.hex(),
        "ld": None if block.layout_digest is None else block.layout_digest.hex(),
        "rm": block.revision,
        "rb": block.restriction_bits,
        "st": 1 if block.tombstoned else 0,
        "dc": export_row.decision_id,
        "pl": None if export_row.payload is None else dict(export_row.payload),
        "x": {k: v for k, v in block.x.items() if k not in _RESERVED_X},
    }
    return {key: record[key] for key in WIRE_KEYS if key in record}


_RESERVED_X: Final = frozenset({"x.ow.cite", "x.ow.addr"})
"""The two slots `import_` borrows in `BlockDraft.x`. See `import_`'s docstring for why.

`x.ow.*` is the framework's reserved vendor segment (03:2745) and matches the `x` key pattern
`^x\\.[a-z0-9_]+\\.[a-z0-9_]+$` at 03:783. `x` is not a digest input (03:2746), so borrowing
these two cannot move a `content_digest`.
"""


def _as_str_or_none(value: object) -> str | None:
    return None if value is None else str(value)


def mark_records(block: Block) -> dict[str, Any] | None:
    """The `marks/NNNNNN.ndjson` record for one block, or `None` when it has no marks.

    `[a, b, kind, value]` per mark, which is `m`'s frozen shape (03:659, :700). See
    `_MARKS_ARE_A_MEMBER` for why the marks live in their own frame-aligned member rather than
    inline on the block record.
    """
    if not block.marks:
        return None
    return {
        "i": str(block.addr),
        "m": [[m.a, m.b, m.kind, m.value] for m in block.marks],
    }


def read_block_record(record: Mapping[str, Any]) -> BlockImport:
    """Decode one wire record. The inverse of `block_record`, field for field.

    Refuses a record missing one of the nineteen `required` keys (03:679) and refuses an unknown
    `k`: 03:2724 makes an unknown `Kind` member the ONE row of the compatibility table that
    refuses rather than tolerates, "which is why adding a kind raises `min_reader`".

    An unknown OPTIONAL key is neither dropped nor fatal. It is preserved under
    `x["x.ow.unknown"]`, the reserved slot of 03:2738-2742, so that `export(import(a)) == a`
    holds rather than almost holds.
    """
    missing = sorted(REQUIRED_KEYS - set(record))
    if missing:
        msg = f"block record {record.get('i')!r} is missing required keys {', '.join(missing)}"
        raise ModelError(msg, fix="ow doc verify <archive>")
    addr = Addr(str(record["i"]))
    quad = None if record.get("q") is None else Quad(*record["q"])
    span = None if record.get("ts") is None else TextSpan(*record["ts"])
    score = record.get("sc")
    unknown = {key: value for key, value in record.items() if key not in _WIRE_KEY_SET}
    extra = dict(record.get("x") or {})
    if unknown:
        extra["x.ow.unknown"] = {**extra.get("x.ow.unknown", {}), **unknown}
    driver, schema_v = record["od"]
    marks = [Mark(a=a, b=b, kind=kind, value=value) for a, b, kind, value in record.get("m") or ()]
    draft = BlockDraft(
        kind=_kind(record["k"]),
        layer=Layer(record["ly"]),
        method=Method(record["mt"]),
        trust=Trust[str(record["tr"]).upper()],
        quote=Quote[str(record["qt"]).upper()],
        text=record["t"],
        label=record.get("lb"),
        raw_kind=record.get("rk"),
        quad=quad,
        origin=_read_origin(record["os"], page=record["p"], quad=quad),
        span=span,
        score=None if score is None else score[0],
        score_kind=None if score is None else score[1],
        payload=record.get("pl"),
        cell=_cell_of(addr),
        marks=marks,
        x=extra,
    )
    layout = record.get("ld")
    return BlockImport(
        addr=addr,
        cite=Cite(str(record["c"])),
        page=record["p"],
        ord=record["o"],
        parent=parent_addr(str(addr)),
        draft=draft,
        producer=record["pd"],
        content_digest=bytes.fromhex(record["cd"]),
        layout_digest=None if layout is None else bytes.fromhex(layout),
        revision=record["rm"],
        restriction_bits=record["rb"],
        tombstoned=bool(record["st"]),
        origin_operator=record["oo"],
        origin_driver=driver,
        driver_schema_v=schema_v,
        decision_id=record.get("dc"),
    )


_WIRE_KEY_SET: Final = frozenset(WIRE_KEYS)

_UNKNOWN_KIND: Final = "OW_SCHEMA_UNKNOWN_KIND"
"""03-document-model.md:2724 names this symbol for an unknown `Kind` on a wire record.

`codes.toml` carries no row for it, so `OwError.numeric()` degrades to `""` -- which errors.py
documents as the designed behaviour for a symbol with no register row, precisely so resolving a
numeric can never fail an error path. The row is owed to W1.3. Reported.
"""

_UPGRADE_FIX: Final = "pip install -U omniweave-core"


def _kind(value: object) -> Kind:
    try:
        return Kind(value)
    except ValueError as exc:
        msg = (
            f"unknown Kind {value!r}: the row is REFUSED, not defaulted to `unknown`, because "
            f"adding a kind raises min_reader (03:2724). This archive needs a newer reader"
        )
        raise ModelError(msg, symbol=_UNKNOWN_KIND, fix=_UPGRADE_FIX) from exc


def _cell_of(addr: str) -> CellPos | None:
    """`CellPos(r, c)` when the last step is `r<r>c<c>`, else `None`. 03:1097's `cell_ref`.

    The spans are 1x1 here and `add_grid` supplies the merge geometry from `grids.ndjson`
    (`GridRow.cells`), because a merged cell's spans are a property of the grid and not of the
    address: 03:1097 makes the step the ORIGIN cell coordinates and nothing else.
    """
    last = addr.rpartition("/")[2]
    if not last.startswith("r") or "c" not in last:
        return None
    row, _, col = last[1:].partition("c")
    return CellPos(r=int(row), c=int(col)) if row.isdigit() and col.isdigit() else None


def _read_origin(record: Mapping[str, Any], *, page: int, quad: Quad | None) -> OriginSpan:
    """Decode `os`. `pixels` rebuilds itself from `p` and `q` (03:781-786).

    `Quad(*ints)` is called here and that is the sanctioned site: `spans.py`'s `Quad` docstring
    fixes the bare eight-int form as "the STORE's decode path and nothing else", against the
    `quad` column's "8 x i32 LE, or NULL" (charter.md:1039). An archive decode is the same
    operation on the same eight ints; `Quad.from_driver` is for DRIVER-frame coordinates
    (INV-9), which an archive never carries because the writer already converted them.
    """
    kind = record.get("k")
    if kind == "bytes":
        return OriginBytes(
            part=record["part"], start=record["a"], length=record["len"], codec=record["codec"]
        )
    if kind == "nodepath":
        return OriginNodePath(part=record["part"], path=tuple(record["path"]))
    if kind == "glyphs":
        return OriginGlyphs(
            part=record["part"],
            extractor=record["extractor"],
            start=record["a"],
            length=record["len"],
        )
    if kind == "pixels":
        if quad is None:
            msg = "an os_kind=pixels record carries its polygon in `q` (03:781) and `q` is null"
            raise ModelError(msg, fix="ow doc verify <archive>")
        return OriginPixels(page=page, quad=quad)
    if kind == "none":
        return OriginNone()
    msg = f"unknown os_kind {kind!r}: the five variants are closed (03:2731 raises min_reader)"
    raise ModelError(msg, symbol=_UNKNOWN_KIND, fix=_UPGRADE_FIX)


def rel_record(row: RelRow) -> dict[str, Any]:
    """One `rels.ndjson` record. Endpoints are addresses (03:2508)."""
    return {
        "src": str(row.src),
        "dst": str(row.dst),
        "k": row.kind.value,
        "pd": row.producer,
        "tr": row.trust.name.lower(),
        "sc": None if row.score is None else [row.score, row.score_kind],
        "oo": row.origin_operator,
        "x": dict(row.x),
    }


def read_rel_record(record: Mapping[str, Any]) -> RelRow:
    score = record.get("sc")
    return RelRow(
        src=Addr(str(record["src"])),
        dst=Addr(str(record["dst"])),
        kind=RelKind(record["k"]),
        producer=record["pd"],
        trust=Trust[str(record["tr"]).upper()],
        origin_operator=record.get("oo", ""),
        score=None if score is None else score[0],
        score_kind=None if score is None else score[1],
        x=dict(record.get("x") or {}),
    )


def grid_record(row: GridRow) -> dict[str, Any]:
    """One `grids.ndjson` record. `row_len` keeps raggedness EXPLICIT (the `table_meta` DDL)."""
    return {
        "i": str(row.table),
        "n_rows": row.n_rows,
        "n_cols": row.n_cols,
        "row_len": list(row.row_len),
        "header_rows": row.header_rows,
        "header_cols": row.header_cols,
        "k": row.kind,
        "recon_strategy": row.recon_strategy,
        "recon_score": row.recon_score,
        "has_merges": 1 if row.has_merges else 0,
        "native_part": row.native_part,
        "native_sha256": row.native_sha256,
        "cells": [list(cell) for cell in row.cells],
    }


def read_grid_record(record: Mapping[str, Any]) -> GridRow:
    return GridRow(
        table=Addr(str(record["i"])),
        n_rows=record["n_rows"],
        n_cols=record["n_cols"],
        row_len=tuple(record.get("row_len") or ()),
        kind=record.get("k", "data"),
        cells=tuple((c[0], c[1], c[2], c[3]) for c in record.get("cells") or ()),
        header_rows=record.get("header_rows", 0),
        header_cols=record.get("header_cols", 0),
        recon_strategy=record.get("recon_strategy"),
        recon_score=record.get("recon_score"),
        has_merges=bool(record.get("has_merges", 0)),
        native_part=record.get("native_part"),
        native_sha256=record.get("native_sha256"),
    )


def _ndjson_line(record: Mapping[str, Any]) -> bytes:
    """One NDJSON line: compact, LF-terminated, no NaN, UTF-8.

    Compact (`separators=(",", ":")`) because a frame is the bulk of the archive and the
    ~75 B/block figure at 03:2652 is measured against a compact encoding, while `manifest.json`
    and `frames.json` are pretty-printed because a human reads them. `sort_keys` is off: the
    caller has already put the keys in `WIRE_KEYS` order, and sorting would silently reorder a
    payload's keys, which ARE a digest input (03:2732).
    """
    body = json.dumps(record, separators=(",", ":"), ensure_ascii=False, allow_nan=False)
    return body.encode("utf-8") + b"\n"


# ---------------------------------------------------------------------------
# 7. The writer.
# ---------------------------------------------------------------------------

_ASSET_SUFFIX: Final = MappingProxyType(
    {
        "image/png": ".png",
        "image/jpeg": ".jpg",
        "image/gif": ".gif",
        "image/webp": ".webp",
        "image/tiff": ".tiff",
        "image/svg+xml": ".svg",
        "application/pdf": ".pdf",
    }
)
"""Media type to member suffix, a CLOSED allowlist with a `.bin` fallback.

14-security.md:294-296 requires that a byte written under a name an attacker chose take its
extension "from the *sniffed* media type against a closed allowlist, never from the remote path
or `Content-Disposition`" -- hyperframes' receipt is a remote host dropping a `.html` into a
served directory. The authoritative allowlist belongs with the sniffer in
`omniweave_core`'s ingest side and is not in the tree; this is the archive's own, and the
suffix is cosmetic here anyway because the member is content-addressed by `sha256` and the
manifest carries `media_type`. Reported.
"""


def _asset_member(row: AssetRow) -> str:
    """`assets/cas/ab/cd/<sha256><ext>` -- the fan-out layout of 03:2489.

    Two levels of two hex characters, which is the same `cas://ab/cd/<sha256>` shape the `part`
    and `asset` DDL writes into `store_ref`, so a member name and a CAS path are one mapping.
    """
    digest = row.sha256
    suffix = _ASSET_SUFFIX.get(row.media_type, ".bin")
    return f"{ASSETS_DIR}{digest[0:2]}/{digest[2:4]}/{digest}{suffix}"


def _part_member(row: PartRow) -> str:
    """`parts/word/document.xml` when the part path is a legal member name, else a safe name.

    03:2487 prints the happy case, but `part.path` is `'file' | 'word/document.xml' |
    'pdf:page=12/content=0'` (the `CREATE TABLE part` comment), and the third form carries a
    `:` -- which `member_name_ok` refuses as an alternate data stream and which no Windows
    reader can extract. So the printed spelling is kept where it is legal and a
    content-addressed fallback is used where it is not; `manifest.parts[]` carries the authority
    either way, since it holds both `path` and `sha256`.
    """
    candidate = f"{PARTS_DIR}{row.path}"
    return candidate if member_name_ok(candidate) else f"{PARTS_DIR}_/{row.sha256}"


def _view_member(row: ViewRow) -> str:
    """`views/md-1-7c3f.md` from `view_id` `md/1/7c3f` -- 03:2490's printed spelling.

    The `view_id` grammar is `spans.py`'s `RenderSpan` check, `<fmt>/<version>/<digest4>`, so
    the member name is that with `/` replaced by `-` and the format as the suffix. Replacing
    rather than nesting keeps every view in one flat directory, which is what makes
    `unzip -l` readable for a document with five views.
    """
    fmt = row.view_id.split("/", 1)[0]
    return f"{VIEWS_DIR}{row.view_id.replace('/', '-')}.{fmt}"


class _Writer:
    """The single pass. Member order is this class's control flow and nothing else.

    **`manifest.json` is written LAST and that is forced, not chosen.** A ZIP local header
    carries its member's sizes, `zipfile` cannot revisit one, and `manifest.counts` plus every
    `frames.json` digest are OUTPUTS of the block stream. The alternative is buffering the whole
    document, which 03:2574-2582 exists to forbid: a 5,000-page document never exists in memory,
    and peak resident state is one frame. Reading is by name through the central directory
    (`unzip -p x.owdoc manifest.json`), so nothing a reader or a human does depends on the
    manifest being first.
    """

    def __init__(self, zf: zipfile.ZipFile) -> None:
        self._zf = zf
        self._frames: list[Frame] = []
        self._counts: dict[str, int] = dict.fromkeys(
            ("blocks", "pages", "marks", "rels", "grids", "diags", "parts", "assets", "views"), 0
        )
        self._pages: set[int] = set()
        self._identity: tuple[int, int] | None = None

    def write(self, source: ExportSource) -> Manifest:
        header = source.header()
        self._write_frames(source, header)
        self._write_ndjson(RELS_MEMBER, (rel_record(r) for r in source.rels()), "rels")
        self._write_ndjson(GRIDS_MEMBER, (grid_record(g) for g in source.grids()), "grids")
        self._write_json_array(DIAGS_MEMBER, list(source.diags()), "diags")
        toc = list(source.toc())
        if toc:
            self._write_json_array(TOC_MEMBER, toc, None)
        parts = self._write_parts(source)
        assets = self._write_assets(source)
        views = self._write_views(source)
        self._member(FRAMES_MEMBER, frames_json(tuple(self._frames)))
        self._counts["frames"] = len(self._frames)
        self._counts["pages"] = len(self._pages)
        manifest = Manifest(
            doc_key=header.doc_key,
            gen=header.gen,
            source=dict(header.source),
            status=header.status,
            declared=dict(header.declared),
            achieved=dict(header.achieved),
            producers=tuple(dict(p) for p in header.producers),
            parts=parts,
            assets=assets,
            views=views,
            confidence=dict(header.confidence),
            timings_ms=dict(header.timings_ms),
            counts=dict(self._counts),
            x=dict(header.x),
        )
        self._member(MANIFEST_MEMBER, manifest_json(manifest))
        return manifest

    def _member(self, name: str, payload: bytes) -> None:
        _require_member_name(name)
        self._zf.writestr(_member_info(name, len(payload)), payload)

    def _write_frames(self, source: ExportSource, header: DocHeader) -> None:
        """Blocks and their frame-aligned marks, closed at `FRAME_TARGET_BLOCKS`.

        Peak resident state is one frame's serialised bytes, which at 8,192 blocks and the
        ~1.1 KB per materialised record of 03:2578 is ~9 MB -- the transient decode buffer
        03:2606 prices at 3 x 8,192 x ~1.1 KB for the three-frame read.
        """
        index = 0
        buffer: list[bytes] = []
        marks: list[bytes] = []
        bounds: list[tuple[int, int]] = []
        for row in source.blocks():
            self._check_single(row, header)
            record = block_record(row)
            buffer.append(_ndjson_line(record))
            bounds.append((record["p"], record["o"]))
            self._pages.add(record["p"])
            mark_row = mark_records(row.block)
            if mark_row is not None:
                marks.append(_ndjson_line(mark_row))
                self._counts["marks"] += len(mark_row["m"])
            if len(buffer) >= FRAME_TARGET_BLOCKS:
                self._close_frame(index, buffer, marks, bounds)
                index, buffer, marks, bounds = index + 1, [], [], []
        if buffer:
            self._close_frame(index, buffer, marks, bounds)

    def _check_single(self, row: BlockExport, header: DocHeader) -> None:
        """An archive holds exactly ONE document and exactly ONE generation (03:2503).

        Asserted over the block stream rather than trusted of the caller, because this is the
        property that makes the deep-golden `rebind()` diff "a diff of two files rather than a
        query inside one" (03:2505): two generations in one archive would make the diff a
        self-join and INV-10's byte-exactness unstateable. `Block` carries `doc_ord` and `gen`,
        so the check costs one tuple comparison per block and needs nothing the writer did not
        already have.
        """
        identity = (row.block.doc_ord, row.block.gen)
        if self._identity is None:
            self._identity = identity
            if identity[1] != header.gen:
                msg = (
                    f"block stream is at generation {identity[1]} and manifest.gen is "
                    f"{header.gen}: an archive names the ONE generation it holds (03:2503)"
                )
                raise ModelError(msg, fix="ow doc export <doc> --gen N")
        elif identity != self._identity:
            msg = (
                f"block stream carries (doc_ord, gen) {identity} after {self._identity}: "
                f"an .owdoc is a single-document, single-generation projection (03:2503)"
            )
            raise ModelError(msg, fix="ow doc export <doc> --gen N")

    def _close_frame(
        self,
        index: int,
        buffer: list[bytes],
        marks: list[bytes],
        bounds: list[tuple[int, int]],
    ) -> None:
        payload = b"".join(buffer)
        path = frame_member(index)
        self._member(path, payload)
        if marks:
            self._member(marks_member(index), b"".join(marks))
        self._frames.append(
            Frame(
                lo_page=bounds[0][0],
                lo_ord=bounds[0][1],
                hi_page=bounds[-1][0],
                hi_ord=bounds[-1][1],
                path=path,
                blocks=len(buffer),
                bytes=len(payload),
                sha256=hashlib.sha256(payload).hexdigest(),
            )
        )
        self._counts["blocks"] += len(buffer)

    def _write_ndjson(
        self, name: str, records: Iterable[Mapping[str, Any]], count_key: str | None
    ) -> None:
        lines = [_ndjson_line(record) for record in records]
        if not lines:
            return
        self._member(name, b"".join(lines))
        if count_key is not None:
            self._counts[count_key] = len(lines)

    def _write_json_array(
        self, name: str, records: list[Mapping[str, Any]], count_key: str | None
    ) -> None:
        if not records:
            return
        body = json.dumps(
            [dict(r) for r in records],
            indent=2,
            separators=(",", ": "),
            ensure_ascii=False,
            allow_nan=False,
        )
        self._member(name, (body + "\n").encode("utf-8"))
        if count_key is not None:
            self._counts[count_key] = len(records)

    def _write_parts(self, source: ExportSource) -> tuple[dict[str, Any], ...]:
        rows: list[dict[str, Any]] = []
        for row, blob in source.parts():
            member = _part_member(row)
            present = row.present and bool(blob)
            if present:
                self._member(member, blob)
            rows.append(
                {
                    "path": row.path,
                    "sha256": row.sha256,
                    "byte_len": row.byte_len,
                    "present": present,
                    "member": member if present else None,
                }
            )
        self._counts["parts"] = len(rows)
        return tuple(rows)

    def _write_assets(self, source: ExportSource) -> tuple[dict[str, Any], ...]:
        rows: list[dict[str, Any]] = []
        for row, blob in source.assets():
            member = _asset_member(row)
            present = row.present and bool(blob)
            if present:
                self._member(member, blob)
            rows.append(
                {
                    "sha256": row.sha256,
                    "media_type": row.media_type,
                    "byte_len": row.byte_len,
                    "present": present,
                    "member": member if present else None,
                    "origin_part": row.origin_part,
                    "width": row.width,
                    "height": row.height,
                    "licence": row.licence,
                    "spdx": row.spdx,
                    "source_url": row.source_url,
                    "restriction_bits": row.restriction_bits,
                    "roles": [[str(addr), role] for addr, role in row.roles],
                }
            )
        self._counts["assets"] = len(rows)
        return tuple(rows)

    def _write_views(self, source: ExportSource) -> tuple[dict[str, Any], ...]:
        rows: list[dict[str, Any]] = []
        for row in source.views():
            member = _view_member(row)
            self._member(member, row.text.encode("utf-8"))
            rows.append(
                {
                    "view_id": row.view_id,
                    "member": member,
                    "sha256": row.sha256,
                    "byte_len": row.byte_len,
                }
            )
        self._counts["views"] = len(rows)
        return tuple(rows)


def export(store: ExportSource, path: str | Path) -> Manifest:
    """Write one generation of one document to `path` as a byte-stable `.owdoc`. 02:249.

    The parameter is spelled `store` because 02-architecture.md:249 names the entry point
    `export(store, path)`; its TYPE is `ExportSource`, which is the smallest read protocol the
    writer needs and is neither of the two frozen store protocols. See `ExportSource`.

    **An archive holds exactly one generation and exactly one document** (03:2503). Both are
    properties of the input rather than assertions the writer can make about a store: what this
    function guarantees is that the archive names its generation in `manifest.json` and carries
    no second `doc_key`. `_Writer._check_single` asserts both over the block stream it actually
    wrote.

    Returns the `Manifest` it wrote, so a caller has the counts without re-opening the file.
    """
    target = Path(path)
    staging = target.with_name(target.name + _ATOMIC_SUFFIX)
    try:
        with (
            staging.open("wb") as raw,
            zipfile.ZipFile(raw, "w", zipfile.ZIP_DEFLATED, compresslevel=_COMPRESSLEVEL) as zf,
        ):
            manifest = _Writer(zf).write(store)
        staging.replace(target)
    except BaseException:
        staging.unlink(missing_ok=True)
        raise
    return manifest


# ---------------------------------------------------------------------------
# 8. The bounded reader. 14-security.md section 2.2, transcribed.
# ---------------------------------------------------------------------------


class _Package:
    """14-security.md:236-248's five steps, in order, with its three reviewer properties.

    The declared size is a cheap pre-filter AND the read is also capped, so "a liar in the
    directory does not pass". The error names the BINDING budget rather than whichever check ran
    last -- anydoc has a test for exactly that
    (`anydoc/src/package/archive.rs:183-198`'s `total_budget_exhaustion_reports_max_total_bytes`
    sets `total_read = MAX_TOTAL_BYTES - 100` and asserts the reported name), and
    `test_archive_owdoc.py` carries omniweave's. And the cache is what makes the budget both
    safe and non-annoying: a hit costs nothing and is not charged, so a legitimate document that
    references one member from many relationships does not exhaust the total. Without step 2 you
    add the budget, real documents start failing, and you raise the cap instead of adding the
    cache.

    The cache is itself bounded by `max_total_bytes` by construction: the counter that admits a
    read is the counter that limits what the cache can accumulate.

    `inflations` counts real decompressions and is not diagnostics-only: 03:2604 makes "two or
    three members" the archive read path's headline property, and a test that asserts the RESULT
    is correct cannot tell a seek from a full scan. Counting is how the claim is checked.
    """

    def __init__(
        self,
        zf: zipfile.ZipFile,
        *,
        max_entry_bytes: int = MAX_ENTRY_BYTES,
        max_total_bytes: int = MAX_CONTAINER_TOTAL_BYTES,
    ) -> None:
        self._zf = zf
        self._entry_cap = effective(max_entry_bytes, None, MAX_ENTRY_BYTES)
        self._total_cap = effective(max_total_bytes, None, MAX_CONTAINER_TOTAL_BYTES)
        self._cache: dict[str, bytes] = {}
        self._total = 0
        self.inflations = 0
        self.names = tuple(info.filename for info in zf.infolist())
        for name in self.names:
            _require_member_name(name)

    def has(self, name: str) -> bool:
        return name in self.names

    def read(self, name: str) -> bytes:
        """One member's bytes, charged once. Raises `ResourceLimit` naming the binding budget."""
        cached = self._cache.get(name)
        if cached is not None:
            return cached
        try:
            info = self._zf.getinfo(name)
        except KeyError as exc:
            msg = f"archive member {name!r} is not in the central directory"
            raise ModelError(msg, fix="ow doc verify <archive>") from exc
        if info.file_size > self._entry_cap:
            msg = (
                f"member {name!r} declares {info.file_size} uncompressed bytes, above "
                f"MAX_ENTRY_BYTES {self._entry_cap}. Refused WITHOUT inflating it"
            )
            raise ResourceLimit(msg, limit="max_entry_bytes", fix="ow config set limits.entry")
        remaining = self._total_cap - self._total
        cap = min(self._entry_cap, remaining)
        self.inflations += 1
        with self._zf.open(name) as handle:
            data = handle.read(cap + 1)
        if len(data) > cap:
            limit = (
                "max_container_total_bytes" if remaining < self._entry_cap else "max_entry_bytes"
            )
            msg = (
                f"member {name!r} exceeded {limit} at {cap} bytes with "
                f"{self._total} already read from this archive"
            )
            raise ResourceLimit(msg, limit=limit, fix=f"ow config set limits.{limit}")
        self._total += len(data)
        self._cache[name] = data
        return data


def _require_manifest(pkg: _Package, name: str) -> None:
    """`manifest.json` is the ONE member fatal to omit (03-document-model.md:2516).

    A separate function so the raise is not inside `OwdocReader.__init__`'s `try`, whose only
    job is to close the ZIP handle on any failure. A `raise` inside a `try` that catches
    `BaseException` reads as a caught error at a glance, and ruff's TRY301 says so.
    """
    if not pkg.has(MANIFEST_MEMBER):
        msg = f"{name} has no {MANIFEST_MEMBER}: it is the ONLY member fatal to omit (03:2516)"
        raise ModelError(msg, fix="ow doc export <doc>")


class OwdocReader:
    """Read a `.owdoc`. The seek path is `blocks(pages=...)` and it is the point (03:2600-2606).

    Open refuses three things and tolerates everything else. It refuses a missing
    `manifest.json` (the one fatal omission, 03:2516), a `container_version` or `model_version`
    MAJOR above this reader's or a `min_reader` above it (03:2517, and there is no `--force`),
    and a member name that is not a legal member name (zip-slip, 14-security.md section 10). A
    missing or unparseable OTHER member yields `status = partial` and a diagnostic on
    `self.diagnostics`, which is 03:2516's tolerance rule with the `Diag` recorded rather than
    raised.

    Not a context manager by accident: the ZIP handle is held open for the life of the reader
    because a seek reads members lazily, so `close()` -- or the `open_owdoc` context manager --
    is how the handle is released.
    """

    def __init__(
        self,
        path: str | Path,
        *,
        max_entry_bytes: int = MAX_ENTRY_BYTES,
        max_total_bytes: int = MAX_CONTAINER_TOTAL_BYTES,
    ) -> None:
        self.path = Path(path)
        self.diagnostics: list[dict[str, Any]] = []
        try:
            self._zf = zipfile.ZipFile(self.path, "r")
        except zipfile.BadZipFile as exc:
            msg = f"{self.path.name} is not a ZIP: an .owdoc is a plain ZIP (03:2494)"
            raise ModelError(msg, fix="ow doc verify <archive>") from exc
        try:
            self._pkg = _Package(
                self._zf, max_entry_bytes=max_entry_bytes, max_total_bytes=max_total_bytes
            )
            _require_manifest(self._pkg, self.path.name)
            self.manifest = parse_manifest(self._pkg.read(MANIFEST_MEMBER))
            require_readable(self.manifest)
            self.frames = self._read_frames()
        except BaseException:
            self._zf.close()
            raise

    @property
    def inflations(self) -> int:
        """How many members this reader has actually decompressed. The seek path's measure."""
        return self._pkg.inflations

    @property
    def status(self) -> str:
        """`manifest.status`, degraded to `partial` if any member was missing or unparseable."""
        return "partial" if self.diagnostics else self.manifest.status

    def close(self) -> None:
        self._zf.close()

    def _diag(self, code: str, member: str, detail: str) -> None:
        self.diagnostics.append(
            {"code": code, "severity": "warning", "member": member, "detail": detail}
        )

    def _read_frames(self) -> tuple[Frame, ...]:
        """`frames.json`, or a reconstructed index over `blocks/*.ndjson` in name order.

        The fallback is what makes 03:2516's tolerance rule true for the frame index without
        making the seek path lie: a reconstructed index has no `(lo_page, lo_ord)` coordinates
        to bisect, so `blocks(pages=...)` degrades to reading every frame and says so with a
        diagnostic. Returning `()` instead would silently answer every page query with nothing.
        """
        if not self._pkg.has(FRAMES_MEMBER):
            self._diag("OW_MODEL", FRAMES_MEMBER, "absent; falling back to a full frame scan")
            return ()
        try:
            return parse_frames_json(self._pkg.read(FRAMES_MEMBER))
        except ModelError as exc:
            self._diag("OW_MODEL", FRAMES_MEMBER, f"unparseable: {exc}")
            return ()

    def _frame_members(self) -> tuple[str, ...]:
        return tuple(sorted(n for n in self._pkg.names if n.startswith(BLOCKS_DIR)))

    def blocks(self, *, pages: range | None = None) -> Iterator[BlockImport]:
        """Every block, or every block on a page in `pages`. THE SEEK PATH.

        With `frames.json` present and `pages` given, this inflates exactly the frames whose
        `(lo_page, hi_page)` span overlaps the range -- two or three of them for a 20-page
        window out of 5,000 pages (03:2600-2604) -- and reads nothing else: not the other
        frames, not the marks of the other frames, not the parts, not the assets. The per-frame
        `sha256` is verified against the inflated bytes on the way past, which 03:2633 makes
        possible without re-deflating.

        A block whose `p` falls outside `pages` is filtered after decode, because a frame is
        block-count-bounded and its first and last pages are partial by construction (03:2626).
        """
        for member, frame in self._selected_frames(pages):
            payload = self._pkg.read(member)
            if frame is not None and hashlib.sha256(payload).hexdigest() != frame.sha256:
                self._diag("OW_INTEGRITY_UNCHECKED", member, "sha256 disagrees with frames.json")
            marks = self._marks_for(member)
            for line in payload.splitlines():
                if not line.strip():
                    continue
                record = json.loads(line)
                if pages is not None and record["p"] not in pages:
                    continue
                inline = record.get("m")
                if inline is None and record["i"] in marks:
                    record = {**record, "m": marks[record["i"]]}
                yield read_block_record(record)

    def _selected_frames(self, pages: range | None) -> tuple[tuple[str, Frame | None], ...]:
        if not self.frames:
            return tuple((member, None) for member in self._frame_members())
        chosen = self.frames if pages is None else frames_overlapping(self.frames, pages)
        return tuple((frame.path, frame) for frame in chosen)

    def _marks_for(self, blocks_member: str) -> dict[str, list[list[Any]]]:
        """The frame-aligned `marks/NNNNNN.ndjson`, or `{}` when the member is absent.

        Absent is normal: a frame whose blocks carry no marks has no marks member, which is why
        this is not a diagnostic.
        """
        member = MARKS_DIR + blocks_member[len(BLOCKS_DIR) :]
        if not self._pkg.has(member):
            return {}
        payload = self._pkg.read(member)
        out: dict[str, list[list[Any]]] = {}
        for line in payload.splitlines():
            if line.strip():
                record = json.loads(line)
                out[record["i"]] = record["m"]
        return out

    def rels(self) -> Iterator[RelRow]:
        yield from (read_rel_record(r) for r in self._ndjson(RELS_MEMBER))

    def grids(self) -> Iterator[GridRow]:
        yield from (read_grid_record(r) for r in self._ndjson(GRIDS_MEMBER))

    def diags(self) -> tuple[Mapping[str, Any], ...]:
        return self._json_array(DIAGS_MEMBER)

    def toc(self) -> tuple[Mapping[str, Any], ...]:
        return self._json_array(TOC_MEMBER)

    def _ndjson(self, member: str) -> Iterator[Mapping[str, Any]]:
        if not self._pkg.has(member):
            return
        try:
            payload = self._pkg.read(member)
        except ModelError as exc:
            self._diag("OW_MODEL", member, f"unreadable: {exc}")
            return
        for number, line in enumerate(payload.splitlines(), start=1):
            if not line.strip():
                continue
            try:
                yield json.loads(line)
            except json.JSONDecodeError as exc:
                self._diag("OW_MODEL", member, f"line {number} is not JSON: {exc}")
                return

    def _json_array(self, member: str) -> tuple[Mapping[str, Any], ...]:
        if not self._pkg.has(member):
            return ()
        try:
            parsed = json.loads(self._pkg.read(member).decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            self._diag("OW_MODEL", member, f"unparseable: {exc}")
            return ()
        if not isinstance(parsed, list):
            self._diag("OW_MODEL", member, "is not a JSON array")
            return ()
        return tuple(parsed)

    def member(self, name: str) -> bytes:
        """One member's bytes, through the bounded reader. Parts, assets and views come out here."""
        return self._pkg.read(name)

    def has_member(self, name: str) -> bool:
        return self._pkg.has(name)


@contextmanager
def open_owdoc(path: str | Path, **kwargs: Any) -> Iterator[OwdocReader]:
    """`with open_owdoc(p) as reader:` -- the reader holds a ZIP handle, so it must be closed."""
    reader = OwdocReader(path, **kwargs)
    try:
        yield reader
    finally:
        reader.close()


# ---------------------------------------------------------------------------
# 9. `import_`. 02-architecture.md:249.
# ---------------------------------------------------------------------------


class DocSinkLike(Protocol):
    """The eleven L2 write methods of 03-document-model.md:547-566, as `import_` calls them.

    **This is not a second declaration of `DocSink`.** `DocSink` is
    `omniweave_core.model`'s (02-architecture.md:248's row 24 lists it there) and is frozen at
    the end of P2; it is not yet in the tree, and `import_` cannot annotate against a name that
    does not exist. When it lands, this protocol is deleted and the annotation becomes
    `DocSink`, because the method set is identical. Three argument types are `model`'s and
    likewise absent -- `DocRecord`, `PageRecord`, `AssetDraft` -- so they are `Any` here and
    `import_` passes its own row types through a factory. Reported.
    """

    def begin_doc(self, rec: Any) -> Any: ...
    def begin_page(self, page: Any) -> None: ...
    def add_block(self, b: BlockDraft) -> Any: ...
    def add_marks(self, b: Any, marks: Sequence[Mark]) -> None: ...
    def add_grid(self, b: Any, g: Any) -> None: ...
    def add_rel(
        self,
        src: Any,
        dst: Any,
        kind: RelKind,
        *,
        trust: Trust,
        score: float | None = None,
        score_kind: str | None = None,
    ) -> None: ...
    def add_asset(self, a: Any, blob: IO[bytes]) -> int: ...
    def add_part(self, path: str, blob: IO[bytes] | None, sha256: bytes, byte_len: int) -> None: ...
    def diag(self, d: Any) -> None: ...
    def end_page(self, stats: Mapping[str, Any]) -> None: ...
    def end_doc(self, status: str) -> Any: ...


def _identity(value: Any) -> Any:
    """The default record factory: hand the sink the archive's own row type.

    A named function rather than a lambda so the default is greppable and so a caller can tell
    from a traceback that no factory was supplied.
    """
    return value


@dataclass(frozen=True, slots=True)
class ImportReport:
    """What an import did, so a caller can compare it against what the archive claimed."""

    doc_key: str
    gen: int
    status: str
    blocks: int
    pages: int
    marks: int
    rels: int
    grids: int
    parts: int
    assets: int
    diagnostics: tuple[Mapping[str, Any], ...]


def import_(
    path: str | Path,
    sink: DocSinkLike,
    *,
    doc_record: Any = _identity,
    page_record: Any = _identity,
    asset_draft: Any = _identity,
) -> ImportReport:
    """Replay one `.owdoc` into a `DocSink`. The other half of G28's round trip. 02:249.

    **Order, and why it is not the order of the write path.** 03:2560-2572's parse sequence buffers
    one page of drafts and commits it at `end_page()`, and `import_` does the same: it reads a
    frame, groups its records by `p`, and emits one page at a time, so peak resident state is one
    page (~132 KB at 120 blocks/page, 03:2578) and never the document. Within a page the drafts
    are ordered by `addr` DEPTH and then `ord`, because `DocSink.add_block` needs a parent's
    `BlockId` before its child's draft can name it and `(page, ord)` order does not supply that:
    `ord` is sibling-local (03:1113). Depth ordering is a topological order of a tree by
    construction.

    **`rel` and `grid` are applied after the last `end_page()`, and that is forced.** A `rel` may
    point from page 3 to page 4, and 03:2233 already puts `add_grid` in the transaction of the
    table's LAST page for a table crossing a page break. An importer has no per-page transaction
    of its own -- the sink owns transactions -- so the only order in which every endpoint has a
    `BlockId` is after the pages. A `DocSink` must therefore accept `add_rel`, `add_grid`,
    `add_part` and `add_asset` between the final `end_page()` and `end_doc()`. Reported.

    **`cite` reaches the sink through `BlockDraft.x`.** `BlockDraft` (03 section 2.6) has no
    `cite` or `addr` field -- the host mints both at `add_block` -- and `add_block`'s signature is
    frozen. But a cite is DURABLE and cannot be re-minted on import: that is precisely why `c` had
    to become a wire key (03:687). So the archive's `cite` and `addr` are carried under
    `x["x.ow.cite"]` and `x["x.ow.addr"]`, in the framework's own reserved vendor segment
    (03:2745), which `x`'s key pattern admits and which is not a digest input (03:2746) so it
    cannot move a `content_digest`. `block_record()` strips both on the way back out. The clean
    fix is a `cite` field on `BlockDraft` or a keyword on `add_block`; both are owned by W2.1 and
    W2.3. Reported.

    `doc_record`, `page_record` and `asset_draft` are the factories that turn this module's row
    types into `model`'s records once those exist. Their defaults pass the row through.
    """
    with open_owdoc(path) as reader:
        return _replay(reader, sink, doc_record, page_record, asset_draft)


def _replay(
    reader: OwdocReader,
    sink: DocSinkLike,
    doc_record: Any,
    page_record: Any,
    asset_draft: Any,
) -> ImportReport:
    manifest = reader.manifest
    header = DocHeader(
        doc_key=manifest.doc_key,
        gen=manifest.gen,
        status=manifest.status,
        source=manifest.source,
        declared=manifest.declared,
        achieved=manifest.achieved,
        producers=manifest.producers,
        confidence=manifest.confidence,
        timings_ms=manifest.timings_ms,
        x=manifest.x,
    )
    sink.begin_doc(doc_record(header))
    # `grids.ndjson` first, and it is small -- one record per table. A cell's merge geometry is a
    # property of the grid, not of its address (03:1097), so a cell's `CellPos` cannot be built
    # without it, and reading it after the blocks would need a second pass over the frames.
    grids = tuple(reader.grids())
    spans = {
        (str(g.table), r, c): (row_span, col_span)
        for g in grids
        for r, c, row_span, col_span in g.cells
    }
    ids: dict[str, Any] = {}
    counters = dict.fromkeys(("blocks", "pages", "marks"), 0)
    for page, rows in _by_page(reader.blocks()):
        sink.begin_page(page_record({"page": page, "gen": manifest.gen}))
        for row in sorted(rows, key=lambda r: (_addr_depth(str(r.addr)), r.ord)):
            ids[str(row.addr)] = _add_one(sink, row, ids, spans, counters)
        sink.end_page({"blocks": len(rows)})
        counters["pages"] += 1
    rels = _apply_rels(sink, reader, ids)
    _apply_grids(sink, grids, ids)
    parts, assets = _apply_blobs(sink, reader, asset_draft)
    for diagnostic in (*reader.diags(), *reader.diagnostics):
        sink.diag(diagnostic)
    status = reader.status
    sink.end_doc(status)
    return ImportReport(
        doc_key=manifest.doc_key,
        gen=manifest.gen,
        status=status,
        blocks=counters["blocks"],
        pages=counters["pages"],
        marks=counters["marks"],
        rels=rels,
        grids=len(grids),
        parts=parts,
        assets=assets,
        diagnostics=tuple(reader.diagnostics),
    )


def _add_one(
    sink: DocSinkLike,
    row: BlockImport,
    ids: Mapping[str, Any],
    spans: Mapping[tuple[str, int, int], tuple[int, int]],
    counters: dict[str, int],
) -> Any:
    draft = row.draft
    draft.parent = None if row.parent is None else ids.get(str(row.parent))
    draft.x = {
        **draft.x,
        "x.ow.addr": str(row.addr),
        "x.ow.cite": str(row.cite),
    }
    if draft.cell is not None:
        table = str(parent_addr(str(row.addr)))
        span = spans.get((table, draft.cell.r, draft.cell.c))
        if span is not None:
            draft.cell = CellPos(r=draft.cell.r, c=draft.cell.c, row_span=span[0], col_span=span[1])
    marks = list(draft.marks)
    draft.marks = []
    block_id = sink.add_block(draft)
    counters["blocks"] += 1
    if marks:
        sink.add_marks(block_id, marks)
        counters["marks"] += len(marks)
    return block_id


def _by_page(rows: Iterable[BlockImport]) -> Iterator[tuple[int, list[BlockImport]]]:
    """Group a `(page, ord)`-ordered stream into pages, holding one page at a time.

    Peak resident state is one page of drafts plus nothing else, which is 03:2565-2568's write
    path exactly: ~132 KB at 120 blocks/page. A 5,000-page document never exists in memory.

    The `document` root is pulled OUT of the grouping and prepended to the first page emitted,
    rather than grouped on its own `p`. Its page is meaningless -- it "spans every page"
    (03:1093) -- so the value stored in `p` is not a fact to sort on, and every page root needs
    the root's `BlockId` before its own draft can name a parent. Prepending puts it in the first
    transaction, and `_addr_depth("doc") == 0` keeps it first within that page's depth ordering
    for free.
    """
    pending_root: list[BlockImport] = []
    current: int | None = None
    batch: list[BlockImport] = []
    for row in rows:
        if str(row.addr) == ROOT_ADDR:
            pending_root.append(row)
            continue
        if current is not None and row.page != current:
            yield current, pending_root + batch
            pending_root, batch = [], []
        current = row.page
        batch.append(row)
    if batch or pending_root:
        page = current if current is not None else pending_root[0].page
        yield page, pending_root + batch


def _apply_rels(sink: DocSinkLike, reader: OwdocReader, ids: Mapping[str, Any]) -> int:
    written = 0
    for rel in reader.rels():
        src, dst = ids.get(str(rel.src)), ids.get(str(rel.dst))
        if src is None or dst is None:
            reader.diagnostics.append(
                {
                    "code": "OW_MODEL",
                    "severity": "warning",
                    "member": RELS_MEMBER,
                    "detail": f"rel {rel.src} -> {rel.dst} names an addr not in this archive",
                }
            )
            continue
        sink.add_rel(
            src, dst, rel.kind, trust=rel.trust, score=rel.score, score_kind=rel.score_kind
        )
        written += 1
    return written


def _apply_grids(sink: DocSinkLike, grids: Sequence[GridRow], ids: Mapping[str, Any]) -> None:
    for grid in grids:
        table = ids.get(str(grid.table))
        if table is not None:
            sink.add_grid(table, grid)


def _apply_blobs(sink: DocSinkLike, reader: OwdocReader, asset_draft: Any) -> tuple[int, int]:
    parts = 0
    for row in reader.manifest.parts:
        member = row.get("member")
        blob = _blob(reader, member) if row.get("present") else None
        sink.add_part(
            str(row["path"]),
            blob,
            bytes.fromhex(str(row["sha256"])),
            int(row["byte_len"]),
        )
        parts += 1
    assets = 0
    for row in reader.manifest.assets:
        member = row.get("member")
        if not row.get("present") or member is None or not reader.has_member(str(member)):
            continue
        blob = _blob(reader, member)
        if blob is None:
            continue
        sink.add_asset(asset_draft(row), blob)
        assets += 1
    return parts, assets


def _blob(reader: OwdocReader, member: object) -> IO[bytes] | None:
    """A member as a seekable stream. `None` when the member is absent (03:2488's `present:false`).

    `io.BytesIO` over the bounded reader's cached bytes rather than `ZipFile.open`, because
    `DocSink.add_part`/`add_asset` take a `BinaryIO` they may seek and a `ZipExtFile` is only
    seekable when the underlying file is -- and because the bytes have already been charged
    against the container budget, so handing back the buffer is the "buffers are shared, never
    copied, on a hit" property of 14-security.md:264.
    """
    if member is None or not reader.has_member(str(member)):
        return None
    return io.BytesIO(reader.member(str(member)))
