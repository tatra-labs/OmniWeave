"""The `.owdoc` codec: the plain-ZIP claim, byte stability, the seek path and the bounded reader.

16-roadmap.md:418 says of this work item that "`unzip -l` and `jq` must both work with no external
tool installed, **which is a test, not a claim**". The stdlib half of that test is the
load-bearing half here and runs everywhere; the `unzip`/`jq` half runs when those binaries happen
to be on PATH and skips otherwise, so the assertion is never vacuous on a bare runner.

The seek path is asserted by COUNTING INFLATIONS rather than by checking the result. 03:2600-2604
makes "reading pages 300-320 out of a 5,000-page `.owdoc` inflates two or three members" the
archive read path's headline property, and a test that only checks the returned blocks passes
identically against a full scan.

Specified in 03-document-model.md sections 3.1, 3.2, 13.2 and 13.3; 14-security.md section 2.2
(the bounded reader) and section 10 (the zip-slip fixture row); 16-roadmap.md:418.
"""

from __future__ import annotations

import ast
import hashlib
import json
import shutil
import struct
import subprocess  # noqa: TID251
import sys
import zipfile
from collections.abc import Iterator, Mapping, Sequence
from pathlib import Path
from typing import Any

import pytest
from omniweave_core.archive import frames as frames_mod
from omniweave_core.archive import manifest as manifest_mod
from omniweave_core.archive import owdoc
from omniweave_core.archive.frames import (
    FRAME_TARGET_BLOCKS,
    Frame,
    frames_overlapping,
    parse_frames_json,
)
from omniweave_core.archive.manifest import (
    CONTAINER_VERSION,
    DIGEST_RECIPE,
    MANIFEST_MEMBER,
    MIN_READER,
    MODEL_VERSION,
    Manifest,
    manifest_json,
    parse_manifest,
    require_readable,
)
from omniweave_core.archive.owdoc import (
    REQUIRED_KEYS,
    WIRE_KEYS,
    BlockExport,
    DocHeader,
    OwdocReader,
    PartRow,
    RelRow,
    ViewRow,
    block_record,
    export,
    import_,
    member_name_ok,
    open_owdoc,
    parent_addr,
    read_block_record,
)
from omniweave_core.errors import ModelError, PolicyRefusal, ResourceLimit
from omniweave_core.model import (
    Addr,
    Block,
    BlockId,
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
    Quad,
    Quote,
    RelKind,
    TextSpan,
    Trust,
)

# `subprocess` is imported above under an explicit TID251 suppression, and the reason is the work
# item's own words. 16-roadmap.md:418 makes "`unzip -l` and `jq` must both work with no external
# tool installed" a TEST rather than a claim, and the only way to test a claim about two external
# binaries is to run them. INV-17's sibling ban (`subprocess` outside `omniweave_core.toolchain`
# and `omniweave_core.host.subproc`) is about the FRAMEWORK not spawning processes off the library
# path; a test that shells out to `unzip` to prove an interoperability claim is the exception the
# ban's own rationale allows, and it is guarded by `shutil.which` so it never runs unless the
# operator has those tools.

_KNOWN_BLOCK_ID = 987_654_321
"""A `block_id` value distinctive enough to grep for in the archive's decompressed bytes.

`1`, `2` and `3` appear in every JSON document ever written, so a grep for a small id proves
nothing. 03:1083 is the rule being tested: `block_id` "never appears in an `.owdoc` archive".
"""

_DOC_KEY = "ab" * 16


def _block(
    addr: str,
    page: int,
    ordinal: int,
    *,
    bid: int = 1,
    cite_n: int | None = None,
    kind: Kind = Kind.PARAGRAPH,
    layer: Layer = Layer.BODY,
    text: str | None = "hi",
    quote: Quote = Quote.VERBATIM,
    origin: Any = None,
    marks: Sequence[Mark] = (),
    gen: int = 3,
    doc_ord: int = 1,
    quad: Quad | None = None,
) -> Block:
    return Block(
        id=BlockId(bid),
        addr=Addr(addr),
        cite=Cite(f"d1#{cite_n if cite_n is not None else 1}"),
        doc_ord=doc_ord,
        gen=gen,
        page=page,
        parent=None,
        ord=ordinal,
        kind=kind,
        raw_kind=None,
        layer=layer,
        label=None,
        text=text,
        content_digest=bytes(range(16)),
        layout_digest=None,
        revision=0,
        quad=quad,
        origin=origin
        if origin is not None
        else OriginBytes(part="file", start=0, length=2, codec="utf-8/strict"),
        span=TextSpan(0, 2) if text else None,
        producer_id=1,
        method=Method.NATIVE,
        trust=Trust.EXTRACTED,
        quote=quote,
        origin_operator="parse.text",
        origin_driver="omniweave.parse.text",
        driver_schema_v=1,
        marks=tuple(marks),
    )


def _root(*, gen: int = 3, doc_ord: int = 1, bid: int = 1) -> Block:
    return _block(
        "doc",
        0,
        0,
        bid=bid,
        kind=Kind.DOCUMENT,
        text=None,
        quote=Quote.SYNTHETIC,
        origin=OriginNone(),
        gen=gen,
        doc_ord=doc_ord,
    )


class Source:
    """A hand-written `ExportSource`. Nine methods, no store, no `sqlite3`."""

    def __init__(
        self,
        blocks: Sequence[BlockExport],
        *,
        rels: Sequence[RelRow] = (),
        grids: Sequence[Any] = (),
        parts: Sequence[tuple[PartRow, bytes]] = (),
        views: Sequence[ViewRow] = (),
        diags: Sequence[Mapping[str, Any]] = (),
        gen: int = 3,
        status: str = "ok",
    ) -> None:
        self._blocks = tuple(blocks)
        self._rels = tuple(rels)
        self._grids = tuple(grids)
        self._parts = tuple(parts)
        self._views = tuple(views)
        self._diags = tuple(diags)
        self._gen = gen
        self._status = status

    def header(self) -> DocHeader:
        return DocHeader(
            doc_key=_DOC_KEY,
            gen=self._gen,
            status=self._status,
            source={"uri": "file:///x.txt", "media_type": "text/plain", "format": "text"},
            declared={"tables": "cells"},
            achieved={"tables": "cells"},
            producers=[{"operator": "parse.text", "op_version": 1}],
        )

    def blocks(self) -> Iterator[BlockExport]:
        yield from self._blocks

    def rels(self) -> Sequence[RelRow]:
        return self._rels

    def grids(self) -> Sequence[Any]:
        return self._grids

    def parts(self) -> Sequence[tuple[PartRow, bytes]]:
        return self._parts

    def assets(self) -> Sequence[Any]:
        return ()

    def views(self) -> Sequence[ViewRow]:
        return self._views

    def diags(self) -> Sequence[Mapping[str, Any]]:
        return self._diags

    def toc(self) -> Sequence[Mapping[str, Any]]:
        return ()


class FakeSink:
    """A hand-written in-memory `DocSink`. It records the call sequence and nothing else.

    G28's `import(export(store)) == store` needs the real SQLite store, which is W2.3's. What can
    be proved without it is that `import_` drives the eleven methods of 03:547-566 in the order
    03:65-70 fixes, that a page is committed by `end_page()` before the next `begin_page()`, and
    that the fields the archive carries arrive intact. That is what this fake is for.
    """

    def __init__(self) -> None:
        self.calls: list[tuple[Any, ...]] = []
        self._next = 0

    def begin_doc(self, rec: Any) -> Any:
        self.calls.append(("begin_doc", rec))
        return rec

    def begin_page(self, page: Any) -> None:
        self.calls.append(("begin_page", page["page"]))

    def add_block(self, b: Any) -> int:
        self._next += 1
        self.calls.append(("add_block", b.x.get("x.ow.addr"), b.x.get("x.ow.cite"), b.parent, b))
        return self._next

    def add_marks(self, b: Any, marks: Sequence[Mark]) -> None:
        self.calls.append(("add_marks", b, tuple(marks)))

    def add_grid(self, b: Any, g: Any) -> None:
        self.calls.append(("add_grid", b, g))

    def add_rel(self, src: Any, dst: Any, kind: RelKind, **kw: Any) -> None:
        self.calls.append(("add_rel", src, dst, kind, kw))

    def add_asset(self, a: Any, blob: Any) -> int:
        self.calls.append(("add_asset", a, blob.read()))
        return 1

    def add_part(self, path: str, blob: Any, sha256: bytes, byte_len: int) -> None:
        self.calls.append(("add_part", path, blob is not None, sha256, byte_len))

    def diag(self, d: Any) -> None:
        self.calls.append(("diag", d))

    def end_page(self, stats: Mapping[str, Any]) -> None:
        self.calls.append(("end_page", stats["blocks"]))

    def end_doc(self, status: str) -> str:
        self.calls.append(("end_doc", status))
        return status

    def names(self) -> list[str]:
        return [call[0] for call in self.calls]


def _tiny_source() -> Source:
    return Source(
        [
            BlockExport(block=_root(), producer=0),
            BlockExport(
                block=_block(
                    "p0/0", 0, 0, bid=_KNOWN_BLOCK_ID, cite_n=2, marks=[Mark(0, 1, "bold", None)]
                ),
                producer=0,
            ),
            BlockExport(block=_block("p0/0/0", 0, 0, bid=7, cite_n=3, text="child"), producer=0),
            BlockExport(
                block=_block("p1/0", 1, 1, bid=8, cite_n=4, text="second page"), producer=0
            ),
        ],
        parts=[(PartRow(path="file", sha256="cd" * 32, byte_len=2, present=True), b"hi")],
    )


@pytest.fixture
def archive(tmp_path: Path) -> Path:
    target = tmp_path / "report.owdoc"
    export(_tiny_source(), target)
    return target


# ---------------------------------------------------------------------------
# 1. "A test, not a claim" -- the plain-ZIP interoperability property.
# ---------------------------------------------------------------------------


def test_every_member_is_deflated_and_no_member_carries_a_zst_suffix(archive: Path) -> None:
    """03:2497: members are `ZIP_DEFLATED`, there is no `.zst` suffix and no zstd on the read path.

    The stated reason is not ratio: `compression.zstd` is Python 3.14+, and
    `unzip -p x.owdoc blocks/000063.ndjson | jq` must need no external decompressor.
    """
    with zipfile.ZipFile(archive) as zf:
        infos = zf.infolist()
    assert infos, "an archive with no members"
    for info in infos:
        assert info.compress_type == zipfile.ZIP_DEFLATED, info.filename
        assert not info.filename.endswith(".zst"), info.filename


def test_every_blocks_member_is_line_delimited_json_that_parses_line_by_line(
    archive: Path,
) -> None:
    """NDJSON means every LINE parses on its own, which is what makes `| jq` work per record."""
    with zipfile.ZipFile(archive) as zf:
        members = [n for n in zf.namelist() if n.startswith("blocks/")]
        assert members
        for member in members:
            raw = zf.read(member).decode("utf-8")
            assert raw.endswith("\n"), member
            lines = raw.splitlines()
            assert lines
            for line in lines:
                record = json.loads(line)
                assert isinstance(record, dict)
                assert set(record) >= REQUIRED_KEYS, sorted(REQUIRED_KEYS - set(record))


def test_manifest_json_and_frames_json_are_indented_for_a_human(archive: Path) -> None:
    """03:2485: `manifest.json` is "Pretty-printed" because `unzip -p` is how it is read."""
    with zipfile.ZipFile(archive) as zf:
        for member in (MANIFEST_MEMBER, "frames.json"):
            raw = zf.read(member).decode("utf-8")
            assert "\n  " in raw, f"{member} is not indented"
            assert json.loads(raw) is not None
            for line in raw.splitlines():
                assert line == line.rstrip(), f"{member} has a trailing space"


@pytest.mark.skipif(shutil.which("unzip") is None, reason="unzip is not on PATH")
def test_unzip_l_lists_the_members_of_the_archive(archive: Path) -> None:
    """The external half of 16-roadmap.md:418. Skipped, never asserted away, when absent."""
    done = subprocess.run(  # noqa: S603
        [str(shutil.which("unzip")), "-l", str(archive)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert done.returncode == 0, done.stderr
    assert "blocks/000000.ndjson" in done.stdout
    assert MANIFEST_MEMBER in done.stdout


@pytest.mark.skipif(
    shutil.which("unzip") is None or shutil.which("jq") is None,
    reason="unzip or jq is not on PATH",
)
def test_unzip_p_piped_into_jq_parses_a_block_frame(archive: Path) -> None:
    """`unzip -p x.owdoc blocks/000000.ndjson | jq .` -- 03:2497's literal sentence, executed."""
    unzipped = subprocess.run(  # noqa: S603
        [str(shutil.which("unzip")), "-p", str(archive), "blocks/000000.ndjson"],
        capture_output=True,
        check=False,
    )
    assert unzipped.returncode == 0, unzipped.stderr
    jq = subprocess.run(  # noqa: S603
        [str(shutil.which("jq")), "."],
        input=unzipped.stdout,
        capture_output=True,
        check=False,
    )
    assert jq.returncode == 0, jq.stderr


# ---------------------------------------------------------------------------
# 2. `block_id` never appears. 03-document-model.md:1083.
# ---------------------------------------------------------------------------


def test_no_member_bytes_carry_the_key_block_id_or_a_known_block_id_value(
    archive: Path,
) -> None:
    """03:1083: `block_id` "never appears in an `.owdoc` archive". Grep the DECOMPRESSED bytes.

    Both halves are needed. The key would catch a writer that emitted a `block_id` field under
    its own name; the value catches one that smuggled it under another key -- which is the more
    likely mistake, because a `pd`, an `rm` or an `x` entry is an integer-shaped hole.
    """
    needle = str(_KNOWN_BLOCK_ID).encode("ascii")
    with zipfile.ZipFile(archive) as zf:
        for name in zf.namelist():
            payload = zf.read(name)
            assert b"block_id" not in payload, name
            assert needle not in payload, f"{name} carries block_id {_KNOWN_BLOCK_ID}"


def test_every_internal_reference_in_the_wire_record_is_an_addr() -> None:
    """03:2508: parent, `rel` endpoints, grid origins, mark owners and asset links are `addr`s."""
    record = block_record(BlockExport(block=_block("p14/3/1", 14, 1, bid=99), producer=0))
    assert record["i"] == "p14/3/1"
    assert record["pa"] == "p14/3"
    rel = owdoc.rel_record(
        RelRow(
            src=Addr("p1/0"),
            dst=Addr("p2/0"),
            kind=RelKind.CONTINUES,
            producer=0,
            trust=Trust.INFERRED,
            origin_operator="derive.spine",
        )
    )
    assert rel["src"] == "p1/0"
    assert rel["dst"] == "p2/0"
    assert "id" not in rel


# ---------------------------------------------------------------------------
# 3. Byte stability. INV-10, 03:2505.
# ---------------------------------------------------------------------------


def test_two_exports_of_one_generation_are_byte_identical(tmp_path: Path) -> None:
    """INV-10 is byte-exactness and 03:2505 makes the deep-golden diff "a diff of two files"."""
    first = tmp_path / "a.owdoc"
    second = tmp_path / "b.owdoc"
    export(_tiny_source(), first)
    export(_tiny_source(), second)
    assert first.read_bytes() == second.read_bytes()


def test_the_zip_date_and_platform_fields_are_pinned_not_sampled(archive: Path) -> None:
    """The two `zipfile` defaults that would break byte stability, asserted individually.

    `ZipInfo(name)` stamps `time.localtime()` and picks `create_system` from `sys.platform`, so a
    same-machine re-export test alone would pass on Windows and fail against a Linux CI runner.
    """
    with zipfile.ZipFile(archive) as zf:
        for info in zf.infolist():
            assert info.date_time == (1980, 1, 1, 0, 0, 0), info.filename
            assert info.create_system == 3, info.filename
            assert info.external_attr == 0o644 << 16, info.filename


def test_a_frames_json_digest_is_over_the_uncompressed_member_bytes(archive: Path) -> None:
    """03:2633: the digest is over the UNCOMPRESSED NDJSON, so a reader can verify what it read.

    This is also the only machine-independent identity the archive has: zlib's deflate output is
    stable for a zlib version and not guaranteed across versions.
    """
    with zipfile.ZipFile(archive) as zf:
        index = parse_frames_json(zf.read("frames.json"))
        for frame in index:
            payload = zf.read(frame.path)
            assert hashlib.sha256(payload).hexdigest() == frame.sha256
            assert frame.bytes == len(payload)
            assert frame.blocks == len(payload.splitlines())


# ---------------------------------------------------------------------------
# 4. The seek path, counted. 03-document-model.md:2600-2604 and section 13.3.
# ---------------------------------------------------------------------------


@pytest.fixture
def multiframe(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Thirteen blocks over twelve pages at a frame target of four: four frames.

    The target is patched down rather than 24,577 blocks being generated, because the property
    under test is the frame INDEX and the bisect over it, and
    `test_the_frame_target_is_eight_thousand_one_hundred_and_ninety_two` keeps the real number
    honest.
    """
    monkeypatch.setattr(owdoc, "FRAME_TARGET_BLOCKS", 4)
    rows = [BlockExport(block=_root(), producer=0)]
    rows += [
        BlockExport(block=_block(f"p{page}/0", page, page, bid=100 + page), producer=0)
        for page in range(12)
    ]
    target = tmp_path / "multi.owdoc"
    export(Source(rows), target)
    return target


def test_a_multiframe_archive_writes_one_member_per_frame(multiframe: Path) -> None:
    with zipfile.ZipFile(multiframe) as zf:
        members = sorted(n for n in zf.namelist() if n.startswith("blocks/"))
        index = parse_frames_json(zf.read("frames.json"))
    assert members == [
        "blocks/000000.ndjson",
        "blocks/000001.ndjson",
        "blocks/000002.ndjson",
        "blocks/000003.ndjson",
    ]
    assert [f.path for f in index] == members
    assert [f.blocks for f in index] == [4, 4, 4, 1]


def test_reading_a_mid_range_inflates_only_the_frames_that_overlap_it(multiframe: Path) -> None:
    """THE work item (16-roadmap.md:418: "the frame index and the seek path are the work").

    Counted, not inferred. The baseline is taken after open because `manifest.json` and
    `frames.json` are inflated to open the archive at all; what is being measured is how many
    BLOCK members a page-ranged read touches.
    """
    with open_owdoc(multiframe) as reader:
        baseline = reader.inflations
        got = [str(b.addr) for b in reader.blocks(pages=range(5, 7))]
        assert reader.inflations - baseline == 1, "one frame covers pages 4-7"
        assert got == ["p5/0", "p6/0"]

    with open_owdoc(multiframe) as reader:
        baseline = reader.inflations
        got = [str(b.addr) for b in reader.blocks(pages=range(2, 4))]
        assert reader.inflations - baseline == 2, "pages 2-3 straddle two frames"
        assert got == ["p2/0", "p3/0"]

    with open_owdoc(multiframe) as reader:
        baseline = reader.inflations
        assert len(list(reader.blocks())) == 13
        assert reader.inflations - baseline == 4, "a full scan reads every frame and no more"


def test_the_frame_index_bisect_answers_the_same_as_a_linear_filter() -> None:
    """`frames_overlapping` is a bisect; a bisect over an unsorted list is plausibly wrong.

    So it is checked against the definition it implements over every window of a synthetic
    index, which is the only way to catch an off-by-one at a frame boundary.
    """
    index = tuple(
        Frame(
            lo_page=n * 10,
            lo_ord=0,
            hi_page=n * 10 + 9,
            hi_ord=5,
            path=f"blocks/{n:06d}.ndjson",
            blocks=4,
            bytes=100,
            sha256="0" * 64,
        )
        for n in range(6)
    )
    for lo in range(60):
        for hi in range(lo, 62):
            want = () if hi <= lo else tuple(f for f in index if f.lo_page < hi and f.hi_page >= lo)
            assert frames_overlapping(index, range(lo, hi)) == want, (lo, hi)


def test_the_frame_target_is_eight_thousand_one_hundred_and_ninety_two() -> None:
    """03-document-model.md:2485 and 16-roadmap.md:418 both say 8,192. Nothing derives it."""
    assert FRAME_TARGET_BLOCKS == 8_192
    assert frames_mod.FRAME_TARGET_BLOCKS == 8_192


def test_a_strided_page_range_is_refused_rather_than_answered_wrong() -> None:
    """A frame bounds a CONTIGUOUS run, so the index cannot answer per-page containment."""
    with pytest.raises(ModelError, match="contiguous page range"):
        frames_overlapping((), range(0, 10, 2))


# ---------------------------------------------------------------------------
# 5. The bounded reader, and the two hostile fixtures. 14-security.md section 2.2, section 10.
# ---------------------------------------------------------------------------


def _hand_zip(path: Path, members: Mapping[str, bytes]) -> Path:
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, payload in members.items():
            info = zipfile.ZipInfo(filename=name, date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            zf.writestr(info, payload)
    return path


def _valid_manifest_bytes() -> bytes:
    return manifest_json(
        Manifest(
            doc_key=_DOC_KEY,
            gen=1,
            source={},
            status="ok",
            declared={},
            achieved={},
        )
    )


@pytest.mark.parametrize(
    "name",
    [
        "../../evil",
        "..",
        "a/../../b",
        "/etc/passwd",
        "C:evil",
        "blocks\\000000.ndjson",
        "con",
        "aux.txt",
        "report.docx:evil",
        "trailing ",
        "trailing.",
        "a//b",
    ],
)
def test_a_hostile_member_name_is_not_a_legal_member_name(name: str) -> None:
    """14-security.md section 10's zip-slip row, plus `confine()`'s name-shape refusals.

    The refusal list is 14-security.md:277-296's, reduced to the clauses that are about the NAME.
    """
    assert not member_name_ok(name)


@pytest.mark.parametrize(
    "name",
    ["manifest.json", "blocks/000000.ndjson", "assets/cas/ab/cd/deadbeef.png", "parts/word/x.xml"],
)
def test_every_name_the_member_tree_prints_is_legal(name: str) -> None:
    """The refusals above must not have taken the archive's own tree with them (03:2480-2492)."""
    assert member_name_ok(name)


def test_an_archive_carrying_a_zip_slip_member_is_refused_at_open(tmp_path: Path) -> None:
    """A member named `../../evil` refuses the whole archive, not just that member.

    `.owdoc` is omniweave's own artefact (14-security.md:1251), so a traversal name in one means
    the file was forged or corrupted -- unlike a third-party container, where 05:773 skips the
    member and counts it. The refusal is `OW_PATH_OUTSIDE_ROOTS`.
    """
    bad = _hand_zip(
        tmp_path / "slip.owdoc",
        {MANIFEST_MEMBER: _valid_manifest_bytes(), "../../evil": b"pwned"},
    )
    with pytest.raises(PolicyRefusal) as caught:
        OwdocReader(bad)
    assert caught.value.code() == "OW_PATH_OUTSIDE_ROOTS"


def _patch_declared_size(path: Path, member: str, size: int) -> None:
    """Rewrite one central-directory entry's uncompressed size. A liar in the directory.

    The central directory is what `zipfile.getinfo().file_size` reads, and it is what
    14-security.md:238's step 1 pre-filters on, so this is exactly the shape of a zip bomb whose
    header claims a gigabyte.
    """
    raw = bytearray(path.read_bytes())
    cursor = 0
    while True:
        cursor = raw.find(b"PK\x01\x02", cursor)
        if cursor < 0:
            msg = f"no central-directory entry for {member}"
            raise AssertionError(msg)
        name_len = struct.unpack_from("<H", raw, cursor + 28)[0]
        name = bytes(raw[cursor + 46 : cursor + 46 + name_len]).decode("utf-8")
        if name == member:
            struct.pack_into("<I", raw, cursor + 24, size)
            path.write_bytes(bytes(raw))
            return
        cursor += 4


def test_a_zip_bomb_is_refused_without_being_inflated(archive: Path) -> None:
    """14-security.md:238: the declared size is a cheap PRE-FILTER, checked before any read.

    "Refused without inflating it" is the property, so the test asserts the inflation counter did
    not move -- a reader that decompressed the member and then measured it would pass a
    result-only assertion and lose the whole point of the pre-filter.
    """
    _patch_declared_size(archive, "blocks/000000.ndjson", 1 << 31)
    with open_owdoc(archive) as reader:
        baseline = reader.inflations
        with pytest.raises(ResourceLimit) as caught:
            list(reader.blocks())
        assert caught.value.limit == "max_entry_bytes"
        assert reader.inflations == baseline, "the bomb was inflated before being refused"


def test_exhausting_the_container_total_names_the_binding_budget(archive: Path) -> None:
    """14-security.md:246-259: the error names the BINDING budget, not whichever check ran last.

    anydoc's own test for this is `total_budget_exhaustion_reports_max_total_bytes`
    (`anydoc/src/package/archive.rs:183-198`), which sets `total_read = MAX_TOTAL_BYTES - 100`
    and asserts the reported name. Here the total is set to exactly what opening the archive
    costs, so the next read has zero remaining while `max_entry_bytes` is still enormous.
    """
    with zipfile.ZipFile(archive) as zf:
        opening_cost = zf.getinfo(MANIFEST_MEMBER).file_size + zf.getinfo("frames.json").file_size
    with open_owdoc(archive, max_total_bytes=opening_cost) as reader:
        with pytest.raises(ResourceLimit) as caught:
            list(reader.blocks())
        assert caught.value.limit == "max_container_total_bytes"


def test_a_cache_hit_is_free_and_is_not_charged_against_the_total(archive: Path) -> None:
    """14-security.md:240 step 2, and :262: without the cache you raise the cap instead.

    The total is set to admit `manifest.json`, `frames.json` and one frame exactly. Reading the
    same frame a second time must succeed and must not inflate again.
    """
    with zipfile.ZipFile(archive) as zf:
        cost = sum(
            zf.getinfo(name).file_size
            for name in (MANIFEST_MEMBER, "frames.json", "blocks/000000.ndjson")
        )
    with open_owdoc(archive, max_total_bytes=cost) as reader:
        first = reader.member("blocks/000000.ndjson")
        after = reader.inflations
        second = reader.member("blocks/000000.ndjson")
        assert first == second
        assert reader.inflations == after, "a cache hit inflated the member again"


def test_a_member_is_never_extracted_to_disk_by_the_reader() -> None:
    """`extractall` is semgrep-banned framework-wide (14-security.md:266); assert it lexically."""
    source = Path(owdoc.__file__).read_text(encoding="utf-8")
    assert ".extractall(" not in source


# ---------------------------------------------------------------------------
# 6. Tolerance and refusal. 03-document-model.md:2510-2519 and section 15.2.
# ---------------------------------------------------------------------------


def test_a_missing_manifest_is_the_one_fatal_omission(tmp_path: Path) -> None:
    """03:2516: "only `manifest.json` is fatal to omit"."""
    bad = _hand_zip(tmp_path / "nomanifest.owdoc", {"frames.json": b"[]\n"})
    with pytest.raises(ModelError, match="ONLY member fatal to omit"):
        OwdocReader(bad)


def test_a_missing_frames_json_is_tolerated_into_partial_status(tmp_path: Path) -> None:
    """03:2516: a missing member yields `status = partial` plus a `Diag`, never a refusal.

    And the fallback must still return the blocks: degrading to `()` frames would answer every
    read with nothing, which is a silent wrong answer rather than a degradation.
    """
    source = _tiny_source()
    full = tmp_path / "full.owdoc"
    export(source, full)
    with zipfile.ZipFile(full) as zf:
        members = {n: zf.read(n) for n in zf.namelist() if n != "frames.json"}
    stripped = _hand_zip(tmp_path / "noframes.owdoc", members)
    with open_owdoc(stripped) as reader:
        assert reader.status == "partial"
        assert any(d["member"] == "frames.json" for d in reader.diagnostics)
        assert len(list(reader.blocks())) == 4
        assert len(list(reader.blocks(pages=range(1, 2)))) == 1


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("container_version", "2.0"),
        ("model_version", "2.0"),
        ("min_reader", "2.0"),
    ],
)
def test_a_major_above_the_reader_is_refused_and_names_the_upgrade(field: str, value: str) -> None:
    """03:2517: refused, naming the version and the upgrade command. There is no `--force`."""
    manifest = Manifest(
        doc_key=_DOC_KEY,
        gen=1,
        source={},
        status="ok",
        declared={},
        achieved={},
        **{field: value},
    )
    with pytest.raises(ModelError) as caught:
        require_readable(manifest)
    assert value in str(caught.value)
    assert caught.value.fix == "pip install -U omniweave-core"


def test_a_minor_above_the_reader_is_not_refused() -> None:
    """03:2723: a new optional field with a new wire key is ignored and preserved, not refused."""
    require_readable(
        Manifest(
            doc_key=_DOC_KEY,
            gen=1,
            source={},
            status="ok",
            declared={},
            achieved={},
            model_version="1.9",
            container_version="1.7",
        )
    )


def test_the_release_one_version_stamps_are_the_plans_own_numbers() -> None:
    """03:2717 fixes all four at release 1. Nothing derives one of them from another."""
    assert (CONTAINER_VERSION, MODEL_VERSION, MIN_READER, DIGEST_RECIPE) == ("1.0", "1.1", "1.0", 1)
    assert manifest_mod.MODEL_VERSION == "1.1"


def test_an_unknown_manifest_key_is_preserved_under_x_ow_unknown() -> None:
    """03:2738-2742: the reserved slot that makes `export(import(a)) == a` hold, not almost hold."""
    raw = json.dumps(
        {
            "container_version": "1.0",
            "model_version": "1.1",
            "min_reader": "1.0",
            "digest_recipe": 1,
            "doc_key": _DOC_KEY,
            "gen": 4,
            "source": {},
            "status": "ok",
            "declared": {},
            "achieved": {},
            "brand_new_key": {"a": 1},
        }
    ).encode("utf-8")
    manifest = parse_manifest(raw)
    assert manifest.x["x.ow.unknown"] == {"brand_new_key": {"a": 1}}
    assert manifest.gen == 4


def test_a_manifest_that_is_not_an_object_or_omits_doc_key_is_refused() -> None:
    with pytest.raises(ModelError, match="is an object"):
        parse_manifest(b"[]")
    with pytest.raises(ModelError, match="missing doc_key"):
        parse_manifest(b'{"gen": 1}')


def test_a_gen_that_arrives_as_a_json_boolean_is_not_read_as_generation_one() -> None:
    """`isinstance(True, int)` is True in Python, which is how a boolean becomes a generation."""
    raw = json.dumps(
        {
            "doc_key": _DOC_KEY,
            "gen": True,
            "source": {},
            "status": "ok",
            "declared": {},
            "achieved": {},
        }
    ).encode("utf-8")
    with pytest.raises(ModelError, match="JSON int"):
        parse_manifest(raw)


# ---------------------------------------------------------------------------
# 7. The wire record. 03-document-model.md sections 3.1 and 3.2.
# ---------------------------------------------------------------------------


def test_the_twenty_nine_wire_keys_are_written_in_the_tables_printed_order() -> None:
    """03:645-679's table order. A record's key order is its bytes, and INV-10 is byte-exactness."""
    assert len(WIRE_KEYS) == 29
    assert len(set(WIRE_KEYS)) == 29
    assert WIRE_KEYS[:5] == ("i", "c", "p", "pa", "o")
    assert WIRE_KEYS[-1] == "x"
    record = block_record(BlockExport(block=_block("p1/0", 1, 0, bid=5), producer=0))
    # `m` is the one key the block record omits, because the marks live in their own
    # frame-aligned member; 03:679 leaves `m` out of `required`, which is what makes that legal.
    assert tuple(record) == tuple(key for key in WIRE_KEYS if key != "m")


def test_the_nineteen_required_keys_are_the_generated_schemas_required_list() -> None:
    """03:679, transcribed. `m` is deliberately NOT required -- see `_MARKS_ARE_A_MEMBER`."""
    assert len(REQUIRED_KEYS) == 19
    assert "m" not in REQUIRED_KEYS
    assert set(WIRE_KEYS) >= REQUIRED_KEYS


def test_an_offset_pair_inside_os_is_a_and_len_while_ts_is_a_half_open_range() -> None:
    """03:671-675: two different quantities never share a letter."""
    record = block_record(
        BlockExport(
            block=_block(
                "p1/0",
                1,
                0,
                bid=5,
                origin=OriginBytes(part="w/d.xml", start=7, length=11, codec="utf-8/strict"),
            ),
            producer=0,
        )
    )
    assert record["os"] == {
        "k": "bytes",
        "part": "w/d.xml",
        "a": 7,
        "len": 11,
        "codec": "utf-8/strict",
    }
    assert record["ts"] == [0, 2]


@pytest.mark.parametrize(
    "origin",
    [
        OriginBytes(part="file", start=3, length=4, codec="utf-8/strict"),
        OriginNodePath(part="w/d.xml", path=(0, 3, 1, 7)),
        OriginGlyphs(part="pdf:page=1", extractor="pdftext@0.6", start=2, length=9),
        OriginPixels(page=4, quad=Quad(0, 0, 10, 0, 10, 10, 0, 10)),
        OriginNone(),
    ],
)
def test_all_five_origin_span_variants_round_trip(origin: Any) -> None:
    """The five are closed (03:2731 raises `min_reader` to add one), so all five are tested."""
    quad = origin.quad if isinstance(origin, OriginPixels) else None
    page = origin.page if isinstance(origin, OriginPixels) else 1
    block = _block("p1/0", page, 0, bid=5, origin=origin, quad=quad)
    back = read_block_record(block_record(BlockExport(block=block, producer=0)))
    assert back.draft.origin == origin


def test_the_pixels_variant_carries_neither_a_page_nor_a_quad_on_the_wire() -> None:
    """03:779-783: the polygon IS the address and is already `q`; the page is already `p`.

    Emitting them twice would create two facts that can disagree.
    """
    quad = Quad(1, 2, 3, 4, 5, 6, 7, 8)
    record = block_record(
        BlockExport(
            block=_block("p9/0", 9, 0, bid=5, origin=OriginPixels(page=9, quad=quad), quad=quad),
            producer=0,
        )
    )
    assert record["os"] == {"k": "pixels"}
    assert record["p"] == 9
    assert record["q"] == [1, 2, 3, 4, 5, 6, 7, 8]


def test_the_wire_record_round_trips_every_field_it_carries() -> None:
    """Encode, decode, re-encode: the second record must be the first, byte for byte."""
    block = _block(
        "p14/3/r2c5",
        14,
        2,
        bid=42,
        cite_n=7,
        marks=[Mark(0, 1, "bold", None), Mark(1, 2, "link", "https://x")],
    )
    row = BlockExport(block=block, producer=3, payload={"lang": "en"}, decision_id="dec-1")
    first = block_record(row)
    back = read_block_record({**first, "m": [[m.a, m.b, m.kind, m.value] for m in block.marks]})
    again = block_record(
        BlockExport(
            block=_block(
                "p14/3/r2c5",
                14,
                2,
                bid=42,
                cite_n=7,
                marks=[Mark(0, 1, "bold", None), Mark(1, 2, "link", "https://x")],
            ),
            producer=3,
            payload={"lang": "en"},
            decision_id="dec-1",
        )
    )
    assert first == again
    assert str(back.addr) == "p14/3/r2c5"
    assert str(back.cite) == "d1#7"
    assert back.parent == Addr("p14/3")
    assert back.producer == 3
    assert back.decision_id == "dec-1"
    assert back.draft.payload == {"lang": "en"}
    assert back.draft.cell is not None
    assert (back.draft.cell.r, back.draft.cell.c) == (2, 5)
    assert [m.kind for m in back.draft.marks] == ["bold", "link"]


def test_an_unknown_kind_is_refused_and_not_defaulted_to_unknown() -> None:
    """03:2724 is the one row of the compatibility table that refuses rather than tolerates."""
    record = block_record(BlockExport(block=_block("p1/0", 1, 0, bid=5), producer=0))
    with pytest.raises(ModelError, match="unknown Kind"):
        read_block_record({**record, "k": "sonnet"})


def test_a_record_missing_a_required_key_is_refused() -> None:
    record = block_record(BlockExport(block=_block("p1/0", 1, 0, bid=5), producer=0))
    del record["cd"]
    with pytest.raises(ModelError, match="missing required keys cd"):
        read_block_record(record)


@pytest.mark.parametrize(
    ("addr", "parent"),
    [
        ("doc", None),
        ("p14/3", "doc"),
        ("p14/3/1", "p14/3"),
        ("p14/3/r2c5", "p14/3"),
        ("p14/3/r2c5/0", "p14/3/r2c5"),
    ],
)
def test_the_parent_addr_is_derived_from_the_child_addr(addr: str, parent: str | None) -> None:
    """03:1091-1105's three rules. Deriving is what removes the `block_id -> addr` map."""
    assert parent_addr(addr) == (None if parent is None else Addr(parent))


def test_marks_travel_in_a_frame_aligned_member_and_not_inline(archive: Path) -> None:
    """The reconciliation of 03:2486 and 03:659 -- one copy, in the member, keyed by `addr`.

    `m` is absent from 03:679's `required` list, which is what makes the split legal.
    """
    with zipfile.ZipFile(archive) as zf:
        blocks = zf.read("blocks/000000.ndjson").decode("utf-8")
        marks = zf.read("marks/000000.ndjson").decode("utf-8")
    for line in blocks.splitlines():
        assert json.loads(line).get("m") is None
    records = [json.loads(line) for line in marks.splitlines()]
    assert records == [{"i": "p0/0", "m": [[0, 1, "bold", None]]}]
    with open_owdoc(archive) as reader:
        by_addr = {str(b.addr): b for b in reader.blocks()}
    assert [m.kind for m in by_addr["p0/0"].draft.marks] == ["bold"]
    assert by_addr["p1/0"].draft.marks == []


def test_an_inline_m_on_a_block_record_is_still_read() -> None:
    """03:2720 makes backward compatibility within a MAJOR unconditional, both directions."""
    record = block_record(BlockExport(block=_block("p1/0", 1, 0, bid=5), producer=0))
    back = read_block_record({**record, "m": [[0, 1, "italic", None]]})
    assert [m.kind for m in back.draft.marks] == ["italic"]


# ---------------------------------------------------------------------------
# 8. One generation, one document. 03-document-model.md:2503.
# ---------------------------------------------------------------------------


def test_a_block_stream_at_a_second_generation_is_refused(tmp_path: Path) -> None:
    """03:2503: exporting two generations of one document is two archives."""
    rows = [
        BlockExport(block=_block("p0/0", 0, 0, bid=1, gen=3), producer=0),
        BlockExport(block=_block("p1/0", 1, 1, bid=2, gen=4), producer=0),
    ]
    with pytest.raises(ModelError, match="single-document, single-generation"):
        export(Source(rows, gen=3), tmp_path / "two.owdoc")


def test_a_block_stream_from_a_second_document_is_refused(tmp_path: Path) -> None:
    rows = [
        BlockExport(block=_block("p0/0", 0, 0, bid=1, doc_ord=1), producer=0),
        BlockExport(block=_block("p1/0", 1, 1, bid=2, doc_ord=2), producer=0),
    ]
    with pytest.raises(ModelError, match="single-document, single-generation"):
        export(Source(rows), tmp_path / "two.owdoc")


def test_a_block_stream_disagreeing_with_the_manifest_generation_is_refused(
    tmp_path: Path,
) -> None:
    rows = [BlockExport(block=_block("p0/0", 0, 0, bid=1, gen=9), producer=0)]
    with pytest.raises(ModelError, match=r"manifest\.gen"):
        export(Source(rows, gen=3), tmp_path / "mismatch.owdoc")


def test_the_manifest_names_the_one_generation_it_holds(archive: Path) -> None:
    """03:2503, which the printed key set at :2482-2484 has no key for. `gen` is that key."""
    with zipfile.ZipFile(archive) as zf:
        record = json.loads(zf.read(MANIFEST_MEMBER))
    assert record["gen"] == 3
    assert record["doc_key"] == _DOC_KEY
    assert list(record)[:6] == [
        "container_version",
        "model_version",
        "min_reader",
        "digest_recipe",
        "doc_key",
        "gen",
    ]


def test_the_manifest_carries_the_seventeen_printed_keys_plus_gen(archive: Path) -> None:
    """03:2482-2484's key set, asserted as a set so a dropped key cannot pass unnoticed."""
    with zipfile.ZipFile(archive) as zf:
        record = json.loads(zf.read(MANIFEST_MEMBER))
    assert set(record) == {
        "container_version",
        "model_version",
        "min_reader",
        "digest_recipe",
        "doc_key",
        "gen",
        "source",
        "status",
        "producers",
        "parts",
        "assets",
        "views",
        "declared",
        "achieved",
        "confidence",
        "timings_ms",
        "counts",
        "x",
    }


# ---------------------------------------------------------------------------
# 9. `import_` against a hand-written `DocSink`. 03-document-model.md:547-566, :65-70.
# ---------------------------------------------------------------------------


def test_import_drives_the_docsink_methods_in_the_order_the_parse_sequence_fixes(
    archive: Path,
) -> None:
    """03:65-70: `begin_doc`, then per page `begin_page` ... `end_page`, then `end_doc`.

    `add_rel`, `add_grid`, `add_part` and `add_asset` land after the final `end_page()` -- see
    `import_`'s docstring for why that is forced rather than chosen.
    """
    sink = FakeSink()
    report = import_(archive, sink)
    assert sink.names() == [
        "begin_doc",
        "begin_page",
        "add_block",
        "add_block",
        "add_marks",
        "add_block",
        "end_page",
        "begin_page",
        "add_block",
        "end_page",
        "add_part",
        "end_doc",
    ]
    assert report.blocks == 4
    assert report.pages == 2
    assert report.marks == 1
    assert report.parts == 1
    assert report.status == "ok"


def test_import_adds_a_parent_before_its_child_within_one_page(archive: Path) -> None:
    """`add_block` needs the parent's `BlockId`, and `(page, ord)` order does not supply it.

    `ord` is sibling-local (03:1113), so the drafts of one page are ordered by `addr` DEPTH --
    which is a topological order of a tree by construction.
    """
    sink = FakeSink()
    import_(archive, sink)
    adds = [c for c in sink.calls if c[0] == "add_block"]
    assert [c[1] for c in adds] == ["doc", "p0/0", "p0/0/0", "p1/0"]
    by_addr = {c[1]: c for c in adds}
    assert by_addr["doc"][3] is None
    assert by_addr["p0/0"][3] == 1, "the page root's parent is the document root's id"
    assert by_addr["p0/0/0"][3] == 2, "the child's parent is the page root's id"


def test_import_carries_the_durable_cite_through_the_reserved_x_slot(archive: Path) -> None:
    """03:687: a cite cannot be re-minted on import, which is why `c` had to become a wire key.

    `BlockDraft` has no `cite` field and `add_block`'s signature is frozen, so the value travels
    in `x["x.ow.cite"]` -- the framework's reserved vendor segment, which is not a digest input.
    """
    sink = FakeSink()
    import_(archive, sink)
    cites = {c[1]: c[2] for c in sink.calls if c[0] == "add_block"}
    assert cites["p0/0"] == "d1#2"
    assert cites["p1/0"] == "d1#4"


def test_the_reserved_x_slots_are_stripped_on_the_way_back_out() -> None:
    """Otherwise a re-export would state a block's identity twice, and `x` is not digested."""
    block = _block("p1/0", 1, 0, bid=5)
    object.__setattr__(block, "x", {"x.ow.cite": "d1#5", "x.vendor.note": "keep"})
    record = block_record(BlockExport(block=block, producer=0))
    assert record["x"] == {"x.vendor.note": "keep"}


def test_import_replays_a_rel_only_when_both_endpoints_are_in_the_archive(
    tmp_path: Path,
) -> None:
    """A dangling endpoint is a diagnostic, not a crash: 03:2516's tolerance, applied to `rel`."""
    rows = [
        BlockExport(block=_root(), producer=0),
        BlockExport(block=_block("p0/0", 0, 0, bid=2), producer=0),
        BlockExport(block=_block("p1/0", 1, 1, bid=3), producer=0),
    ]
    rels = [
        RelRow(
            src=Addr("p0/0"),
            dst=Addr("p1/0"),
            kind=RelKind.CONTINUES,
            producer=0,
            trust=Trust.INFERRED,
            origin_operator="derive.spine",
        ),
        RelRow(
            src=Addr("p0/0"),
            dst=Addr("p99/0"),
            kind=RelKind.NOTE_REF,
            producer=0,
            trust=Trust.INFERRED,
            origin_operator="derive.spine",
        ),
    ]
    target = tmp_path / "rels.owdoc"
    export(Source(rows, rels=rels), target)
    sink = FakeSink()
    report = import_(target, sink)
    assert report.rels == 1
    assert [c[3] for c in sink.calls if c[0] == "add_rel"] == [RelKind.CONTINUES]
    assert any("p99/0" in str(d.get("detail")) for d in report.diagnostics)


def test_import_hands_a_retained_part_a_stream_and_an_unretained_one_none(
    tmp_path: Path,
) -> None:
    """03:2488 and the `part` DDL: `blob = None` IS the retention policy, in the signature."""
    rows = [BlockExport(block=_block("p0/0", 0, 0, bid=2), producer=0)]
    parts = [
        (PartRow(path="file", sha256="ab" * 32, byte_len=2, present=True), b"hi"),
        (PartRow(path="w/d.xml", sha256="ef" * 32, byte_len=99, present=False), b""),
    ]
    target = tmp_path / "parts.owdoc"
    export(Source(rows, parts=parts), target)
    sink = FakeSink()
    import_(target, sink)
    seen = {c[1]: c[2] for c in sink.calls if c[0] == "add_part"}
    assert seen == {"file": True, "w/d.xml": False}


def test_a_part_path_that_is_not_a_legal_member_name_is_content_addressed(
    tmp_path: Path,
) -> None:
    """`part.path` may be `pdf:page=12/content=0`, which no ZIP reader can extract by name."""
    rows = [BlockExport(block=_block("p0/0", 0, 0, bid=2), producer=0)]
    digest = "1a" * 32
    parts = [(PartRow(path="pdf:page=12/content=0", sha256=digest, byte_len=1, present=True), b"x")]
    target = tmp_path / "oddpart.owdoc"
    manifest = export(Source(rows, parts=parts), target)
    assert manifest.parts[0]["member"] == f"parts/_/{digest}"
    with zipfile.ZipFile(target) as zf:
        assert f"parts/_/{digest}" in zf.namelist()
    with open_owdoc(target) as reader:
        assert reader.manifest.parts[0]["path"] == "pdf:page=12/content=0"


def test_a_view_becomes_a_flat_member_named_after_its_view_id(tmp_path: Path) -> None:
    """03:2490's printed spelling `views/md-1-7c3f.md`, from the `view_id` `md/1/7c3f`."""
    rows = [BlockExport(block=_block("p0/0", 0, 0, bid=2), producer=0)]
    views = [ViewRow(view_id="md/1/7c3f", sha256="0" * 64, byte_len=3, text="# x")]
    target = tmp_path / "views.owdoc"
    manifest = export(Source(rows, views=views), target)
    assert manifest.views[0]["member"] == "views/md-1-7c3f.md"
    with zipfile.ZipFile(target) as zf:
        assert zf.read("views/md-1-7c3f.md") == b"# x"


def test_a_diags_member_is_replayed_into_the_sink(tmp_path: Path) -> None:
    """ "Failure is a FIELD, not an exception" (the `diag` DDL)."""
    rows = [BlockExport(block=_block("p0/0", 0, 0, bid=2), producer=0)]
    diags = [{"code": "OW_TEXT_SPLIT", "severity": "info", "message": "split"}]
    target = tmp_path / "diags.owdoc"
    export(Source(rows, diags=diags), target)
    sink = FakeSink()
    import_(target, sink)
    assert [c[1]["code"] for c in sink.calls if c[0] == "diag"] == ["OW_TEXT_SPLIT"]


# ---------------------------------------------------------------------------
# 10. Laziness. G17, INV-17.
# ---------------------------------------------------------------------------


def test_importing_the_archive_subpackage_loads_no_sqlite3() -> None:
    """INV-17: `sqlite3` is legal only under `omniweave_core/store/`. An archive is a file."""
    done = subprocess.run(  # noqa: S603
        [
            _python(),
            "-c",
            "import sys, omniweave_core.archive as a; "
            "assert 'sqlite3' not in sys.modules, sorted(sys.modules); print(a.export.__name__)",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert done.returncode == 0, done.stderr
    assert done.stdout.strip() == "export"


def test_importing_omniweave_core_still_loads_none_of_the_nine_lazy_names() -> None:
    """G17. Landing `archive/` must not have made `import omniweave_core` pay for it."""
    nine = [
        "model",
        "store",
        "archive",
        "retrieve",
        "answer",
        "out",
        "host",
        "toolchain",
        "modelserver",
    ]
    done = subprocess.run(  # noqa: S603
        [
            _python(),
            "-c",
            "import sys, omniweave_core\n"
            f"leaked = [n for n in {nine!r} if f'omniweave_core.{{n}}' in sys.modules]\n"
            "assert not leaked, leaked\n"
            "print('clean')",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert done.returncode == 0, done.stderr
    assert done.stdout.strip() == "clean"


def _python() -> str:
    """This interpreter, so a subprocess probe runs inside the same virtual environment."""
    return sys.executable


# ---------------------------------------------------------------------------------------------
# OUT15, relocated: this module is the second ZIP writer, so it carries the ban's guarantee
# ---------------------------------------------------------------------------------------------
#
# `omniweave-no-zipfile-write-outside-opc` excludes `owdoc.py` because a `.owdoc` IS a plain ZIP
# (03-document-model.md:2485-2501) and 16-roadmap.md:418 asks for the writer at P2, seven phases
# before `out/opc.py` exists (W9.1). Seven plan sites nonetheless call `opc.py` "the only
# zipfile-for-write in the framework"; the contradiction and its ruling are
# `_plan/_notes/build-defects.md` D13.
#
# The exclusion is only defensible if the property the ban protected still holds here, and these
# two tests are where it does. They are TESTS and not a new semgrep rule on purpose: the bank is a
# transcription of 02-architecture.md:392's list, and
# `test_semgrep_bank.py::test_the_bank_carries_no_rule_the_plan_did_not_order` exists precisely to
# stop someone inventing a site ban and filing it as though the plan had ordered it.


def _owdoc_source() -> str:
    """`owdoc.py`'s own text, read from the installed package rather than a guessed path."""
    return Path(owdoc.__file__).read_text(encoding="utf-8")


def test_every_zip_member_write_passes_a_pinned_zipinfo_and_never_a_bare_name() -> None:
    """The determinism half of OUT15, asserted over this module's `ast`.

    `ZipFile.writestr("name", data)` and `ZipFile.write(path)` stamp `time.localtime()` into
    `date_time` and read `create_system` off `sys.platform`, so one generation exported twice --
    or exported on two machines -- is two different files. 01-principles.md:684 states it in
    general ("only `ZipInfo(name)` yields the safe" result) and the semgrep rule's own message
    gives it as the reason the ban exists at all.

    It matters here more than it does in `out/`: INV-10 is byte-exactness, and
    03-document-model.md:2505 makes the deep-golden `rebind()` diff "a diff of two files rather
    than" a comparison of parsed structures. A local-clock `date_time` would move those bytes on
    every run and the golden set would be unusable.

    A `str` first argument is the defect and anything else passes -- this is a shape check, not a
    type checker. `test_two_exports_of_one_generation_are_byte_identical` is what catches the case
    a shape check cannot see, and neither test replaces the other: this one names the mistake at
    the line that made it, and that one proves the result.
    """
    tree = ast.parse(_owdoc_source())
    offenders: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
            continue
        if node.func.attr not in {"writestr", "write"}:
            continue
        first = node.args[0] if node.args else None
        if isinstance(first, ast.Constant) and isinstance(first.value, str):
            offenders.append(f"owdoc.py:{node.lineno}: {node.func.attr}({first.value!r}, ...)")
    assert offenders == [], (
        "a ZIP member written with a str name stamps the local clock into date_time. "
        f"Pass a pinned ZipInfo -- `_member_info(name)`. Offenders: {offenders}"
    )


def test_that_zipinfo_check_would_actually_fire() -> None:
    """The mutation, kept, because the check above passes on a clean file either way.

    Without it the assertion is indistinguishable from `assert [] == []`: it walks a real tree,
    finds nothing, and is green whether or not the predicate is correct. The project has been
    bitten by exactly this shape twice -- a gate whose fixture could not have shown the opposite
    answer is not evidence.
    """

    def offenders(source: str) -> list[int]:
        return [
            node.lineno
            for node in ast.walk(ast.parse(source))
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr in {"writestr", "write"}
            and node.args
            and isinstance(node.args[0], ast.Constant)
            and isinstance(node.args[0].value, str)
        ]

    assert offenders('zf.writestr("manifest.json", payload)\n') == [1]
    assert offenders('zf.write("frames.json")\n') == [1]
    assert offenders('zf.writestr(_member_info("manifest.json"), payload)\n') == []
    assert offenders("zf.writestr(info, payload)\n") == []


def test_the_only_zipfile_open_for_write_in_the_archive_is_in_this_one_module() -> None:
    """The exclusion is one FILE, not the package, and the sibling modules must stay clean.

    `frames.py`, `manifest.py`, `owcheck.py` and `__init__.py` are not excluded from
    `omniweave-no-zipfile-write-outside-opc`, so a ZIP opened for writing in any of them is a
    semgrep failure. Asserted here as well because a reader of this file should be able to see the
    scope of the exemption without reconstructing it from a YAML `paths.exclude` list.
    """
    package = Path(owdoc.__file__).parent
    writers: list[str] = []
    for path in sorted(package.glob("*.py")):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            name = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", None)
            if name != "ZipFile":
                continue
            mode = node.args[1] if len(node.args) > 1 else None
            literal = mode.value if isinstance(mode, ast.Constant) else None
            for keyword in node.keywords:
                if keyword.arg == "mode" and isinstance(keyword.value, ast.Constant):
                    literal = keyword.value.value
            if isinstance(literal, str) and literal[:1] in {"w", "a", "x"}:
                writers.append(f"{path.name}:{node.lineno}")
    assert all(entry.startswith("owdoc.py:") for entry in writers), (
        f"only owdoc.py is excluded from the ZIP-write ban; found writes in {writers}"
    )
    assert writers, "no ZIP-for-write found at all -- this test would be vacuous"
