"""`fixtures/gen/gen_5000p_pdf.py` -- the generator regime, and the bytes it actually writes.

13-quality.md:586-589 states the regime in one sentence and every clause of it is a claim this
file has to check: *"`fixtures/gen/*.py`, each deterministic under `SOURCE_DATE_EPOCH=0` with
`random`, `secrets`, `uuid4`, `time.time` and `datetime.now` monkeypatched to raise... Output
lands in `fixtures/generated/`, which is `.gitignore`d; `fixtures/gen/EXPECTED.sha256` pins each
generator's output so a generator change is a one-line visible diff rather than a silent corpus
change."*

**The five patches are installed, not assumed.** A generator that happens not to call `time.time`
today is a different artefact from one that provably cannot, and the difference shows up on the
day someone adds a `/CreationDate` from the clock. `_forbid_the_five_clocks` replaces all five
with a raiser and the tests that use it FIRST assert that the raiser bites -- a harness that
silently patched nothing would make every determinism test below vacuous.

**Why the structural assertions are on the bytes and not on a PDF library.** The P2 stub driver
(`tools/p2_stub_parse.py`) locates every text literal by its offset IN THE FILE and turns that
offset into an `OriginBytes`, which is what lets `ow store verify` re-derive `content_sha256` from
stored bytes (16-roadmap.md:442-443). So the load-bearing properties are byte-level and nothing
else can check them: a `/Length` that disagrees with its stream, an xref offset that points one
byte past its object, or a single carriage return introduced by a text-mode write would each
leave a file that most viewers still render and every offset in the store wrong. Those are the
four things a PDF library would happily hide, so this file parses the raw bytes itself.

**The pins.** `EXPECTED.sha256`'s eight-page line is regenerated and compared here in about a
tenth of a second; the 5,000-page line is regenerated too, because at ~1.2 s and ~29 MB it is
still cheaper than an unchecked pin, and an unchecked pin is exactly the "silent corpus change"
13-quality.md:588 is guarding against. Both hashes are literals in a committed file that the
generator does not read -- neither side of either comparison comes out of the thing under test.

Specified against: 13-quality.md:586-589, 16-roadmap.md:442-460, 12-performance.md:244-245,
07-store-and-retrieval.md:1005-1030, 00-vision.md:474 and ruling D27 (this session).
"""

from __future__ import annotations

import ast
import datetime
import hashlib
import importlib.util
import re
import sys
from pathlib import Path
from typing import Final, NamedTuple

import pytest


def _repo_root(start: Path) -> Path:
    """The workspace root, found by walking up rather than by counting `parents[n]`."""
    for candidate in (start, *start.parents):
        if (candidate / "pyproject.toml").is_file() and (candidate / "packages").is_dir():
            return candidate
    message = f"no omniweave workspace root above {start}"
    raise RuntimeError(message)


REPO_ROOT: Final = _repo_root(Path(__file__).resolve())
GEN_PATH: Final = REPO_ROOT / "fixtures" / "gen" / "gen_5000p_pdf.py"
EXPECTED_PATH: Final = REPO_ROOT / "fixtures" / "gen" / "EXPECTED.sha256"
GITIGNORE: Final = REPO_ROOT / ".gitignore"

# The generator is a script under `fixtures/gen/`, not a distribution, so there is no package to
# import it from. `spec_from_file_location` loads it by path -- the same mechanism
# `test_gate_crash.py` uses for `tools/gate_crash.py`, and for the same reasons: not
# `importlib.import_module`, which is banned outside `host/`, and not a `sys.path` mutation,
# which would leak into every later test.
_SPEC = importlib.util.spec_from_file_location("omniweave_gen_5000p_pdf", GEN_PATH)
if _SPEC is None or _SPEC.loader is None:  # pragma: no cover -- the file is in this repository.
    message = f"cannot load {GEN_PATH}"
    raise RuntimeError(message)
gen = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = gen
_SPEC.loader.exec_module(gen)

SMALL_PAGES: Final = 8
"""The page count `EXPECTED.sha256`'s small pin covers, and what nearly every test below uses."""

EPS: Final = 5e-4
"""Half of the last emitted decimal place. Every number in the file has three decimals, so two
positions that differ by less than this were written from the same value."""


# ---------------------------------------------------------------------------------------------
# A parser for exactly the grammar the generator emits, and nothing else
# ---------------------------------------------------------------------------------------------

_STREAM_RE: Final = re.compile(rb"(\d+) 0 obj\n<< /Length (\d+) >>\nstream\n")
_TF_RE: Final = re.compile(rb"^/F1 (\d+\.\d{3}) Tf$")
_TF_LINE_RE: Final = re.compile(rb"^/F1 (\d+\.\d{3}) Tf$", re.MULTILINE)
_TM_RE: Final = re.compile(rb"^1 0 0 1 (-?\d+\.\d{3}) (-?\d+\.\d{3}) Tm$")
_TJ_RE: Final = re.compile(rb"^\((.*)\) Tj$", re.DOTALL)
_DATE_RE: Final = re.compile(rb"D:\d{14}Z")


class Stream(NamedTuple):
    """One content-stream object as it sits in the file."""

    obj: int
    declared_length: int
    start: int
    """File offset of the first byte of stream data."""
    data: bytes


class Run(NamedTuple):
    """One `Tm`/`Tj` pair, with the size from the most recent `Tf`."""

    size: float
    x: float
    y: float
    text: str
    literal: bytes
    """The literal body AS WRITTEN, escapes included."""


def _streams(data: bytes) -> list[Stream]:
    """Every content stream, in file order -- which is page order."""
    out: list[Stream] = []
    for match in _STREAM_RE.finditer(data):
        length = int(match.group(2))
        start = match.end()
        out.append(Stream(int(match.group(1)), length, start, data[start : start + length]))
    return out


def _unescape(literal: bytes) -> str:
    r"""The stub driver's unescaper, written independently here.

    Left to right, because `\\(` is a backslash followed by an open parenthesis and a naive chain
    of three `replace` calls in the wrong order turns it into an escaped parenthesis.
    """
    out = bytearray()
    index = 0
    while index < len(literal):
        byte = literal[index]
        if byte == 0x5C:  # backslash
            assert index + 1 < len(literal), f"trailing backslash in {literal!r}"
            following = literal[index + 1]
            assert following in (0x5C, 0x28, 0x29), f"unknown escape in {literal!r}"
            out.append(following)
            index += 2
            continue
        assert byte not in (0x28, 0x29), f"unescaped parenthesis in {literal!r}"
        out.append(byte)
        index += 1
    return out.decode("ascii")


def _runs(stream: bytes) -> list[Run]:
    """Parse one content stream to runs, failing on any line outside the frozen grammar."""
    lines = stream.split(b"\n")
    assert lines[0] == b"BT"
    assert lines[-1] == b"ET"
    runs: list[Run] = []
    size: float | None = None
    pending: tuple[float, float] | None = None
    for line in lines[1:-1]:
        if (tf := _TF_RE.match(line)) is not None:
            size = float(tf.group(1))
            continue
        if (tm := _TM_RE.match(line)) is not None:
            assert pending is None, "two Tm in a row"
            pending = (float(tm.group(1)), float(tm.group(2)))
            continue
        tj = _TJ_RE.match(line)
        assert tj is not None, f"line outside the grammar: {line!r}"
        assert pending is not None, "a Tj with no Tm before it"
        assert size is not None, "a Tj before any Tf"
        literal = tj.group(1)
        runs.append(Run(size, pending[0], pending[1], _unescape(literal), literal))
        pending = None
    assert pending is None, "a trailing Tm with no Tj"
    return runs


@pytest.fixture(scope="module")
def small_pdf(tmp_path_factory: pytest.TempPathFactory) -> bytes:
    """`--pages 8`, generated once and read back. Every structural test reads these bytes."""
    out = tmp_path_factory.mktemp("gen") / f"gen_{SMALL_PAGES}p.pdf"
    gen.generate(out, pages=SMALL_PAGES)
    return out.read_bytes()


# ---------------------------------------------------------------------------------------------
# The file is a real PDF
# ---------------------------------------------------------------------------------------------


def test_the_file_opens_with_the_header_and_the_binary_comment(small_pdf: bytes) -> None:
    """`%PDF-1.4` then four bytes >= 0x80 on a comment line.

    The binary comment is what tells every downstream tool the file is binary rather than text,
    and it is therefore the first line of defence against the CRLF translation that would rot
    every byte offset the stub driver emits.
    """
    assert small_pdf.startswith(b"%PDF-1.4\n%")
    comment = small_pdf.split(b"\n")[1]
    assert comment[:1] == b"%"
    assert len(comment) == 5
    assert all(byte >= 0x80 for byte in comment[1:])


def test_the_file_ends_with_the_end_of_file_marker(small_pdf: bytes) -> None:
    assert small_pdf.endswith(b"%%EOF\n")


def test_no_byte_in_the_file_is_a_carriage_return(small_pdf: bytes) -> None:
    """A CRLF translation on a Windows checkout would shift every literal by one byte per line
    above it, which would leave a file that still renders and an `OriginBytes` that points at the
    wrong bytes -- a silent `content_sha256` failure at `ow store verify` rather than a loud one.
    The generator writes `"wb"` and never emits a CR; this is the assertion that keeps it so."""
    assert b"\r" not in small_pdf


def test_every_declared_length_is_the_true_byte_count_of_its_stream(small_pdf: bytes) -> None:
    """`/Length` is the one number a parser trusts without checking, so it is checked here twice:
    `endstream` must begin exactly `/Length` bytes after the stream data starts, and the distance
    to the next `endstream` found by search must equal the same number."""
    streams = _streams(small_pdf)
    assert len(streams) == SMALL_PAGES
    for stream in streams:
        tail = stream.start + stream.declared_length
        assert small_pdf[tail : tail + len(b"\nendstream\nendobj\n")] == b"\nendstream\nendobj\n"
        found = small_pdf.index(b"\nendstream", stream.start)
        assert found - stream.start == stream.declared_length


def test_no_stream_carries_a_filter(small_pdf: bytes) -> None:
    """Uncompressed everywhere: a literal in the stream is a literal in the file, which is the
    whole reason the stub driver can work without a PDF library."""
    assert b"/Filter" not in small_pdf


def test_every_xref_offset_points_at_the_object_it_claims(small_pdf: bytes) -> None:
    """A classic cross-reference TABLE, twenty bytes per entry, every entry verified against the
    bytes it addresses. An off-by-one here is the failure mode that makes the whole fixture
    useless while still looking like a PDF."""
    marker = b"\nstartxref\n"
    startxref = int(small_pdf[small_pdf.rindex(marker) + len(marker) :].split(b"\n")[0])
    assert small_pdf[startxref : startxref + 5] == b"xref\n"

    count = gen.object_count(SMALL_PAGES)
    header = f"xref\n0 {count + 1}\n".encode("ascii")
    assert small_pdf[startxref : startxref + len(header)] == header

    table = startxref + len(header)
    assert small_pdf[table : table + 20] == gen.XREF_FREE_ENTRY
    for number in range(1, count + 1):
        entry = small_pdf[table + 20 * number : table + 20 * (number + 1)]
        assert len(entry) == 20
        assert entry.endswith(b" 00000 n \n")
        offset = int(entry[:10])
        assert small_pdf[offset:].startswith(f"{number} 0 obj\n".encode("ascii"))


def test_the_trailer_size_is_one_more_than_the_object_count(small_pdf: bytes) -> None:
    """`/Size` counts object 0, the head of the free list, which is why it is not the number of
    objects the generator wrote."""
    count = gen.object_count(SMALL_PAGES)
    assert count == 4 + 2 * SMALL_PAGES
    assert f"/Size {count + 1} ".encode("ascii") in small_pdf
    assert len(re.findall(rb"^\d+ 0 obj$", small_pdf, re.MULTILINE)) == count


def test_every_page_declares_the_a4_media_box(small_pdf: bytes) -> None:
    """`[0 0 595.276 841.890]`, trailing zero intact: one number format for the whole file."""
    boxes = re.findall(rb"/MediaBox \[0 0 595\.276 841\.890\]", small_pdf)
    assert len(boxes) == SMALL_PAGES


def test_every_date_in_the_file_is_the_frozen_literal(small_pdf: bytes) -> None:
    """13-quality.md:586-589 forbids the clock; `D:19800101000000Z` is what replaces it, and a
    generator that grew a second date source would be caught here rather than by a hash diff
    nobody can explain."""
    dates = _DATE_RE.findall(small_pdf)
    assert dates
    assert set(dates) == {gen.FIXED_DATE.encode("ascii")}


# ---------------------------------------------------------------------------------------------
# The page, as the stub driver has to read it
# ---------------------------------------------------------------------------------------------


def test_a_page_holds_eighty_seven_text_runs(small_pdf: bytes) -> None:
    """1 heading + 8 x 4 body lines + 9 x 6 cells. The frozen contract's number, checked against
    the emitted bytes rather than against the constants that produced them."""
    assert gen.RUNS_PER_PAGE == 87
    for stream in _streams(small_pdf):
        assert len(_runs(stream.data)) == 87


def test_a_content_stream_holds_no_operator_outside_bt_tf_tm_tj_and_et(small_pdf: bytes) -> None:
    """No `Td`, no `TJ`, no `TL`, no `T*`. `_runs` rejects any line outside the grammar, so this
    test is that rejection applied to every page, plus a direct scan for the four operators the
    contract names as absent -- because a grammar checker can only reject what reaches it."""
    for stream in _streams(small_pdf):
        _runs(stream.data)
        for banned in (b" Td\n", b" TJ\n", b" TL\n", b"\nT*\n"):
            assert banned not in stream.data


def test_the_three_font_sizes_appear_once_each_per_page_and_in_emission_order(
    small_pdf: bytes,
) -> None:
    """One `Tf` per size change: heading, body, cells. Three lines, never eighty-seven."""
    for stream in _streams(small_pdf):
        sizes = [float(match) for match in _TF_LINE_RE.findall(stream.data)]
        assert sizes == [gen.HEADING_SIZE_PT, gen.BODY_SIZE_PT, gen.CELL_SIZE_PT]


def test_a_paragraph_drops_by_exactly_the_leading_and_every_other_gap_is_larger(
    small_pdf: bytes,
) -> None:
    """The coalescing rule the stub driver depends on, asserted on both sides.

    Inside one paragraph the baseline drops by EXACTLY `LEADING_PT`; at the heading boundary, at
    every paragraph boundary and at the table boundary it drops by strictly more. If any gap in
    the second class ever equalled 12.0 the stub would merge two paragraphs into one and the
    fixture would silently stop testing what it exists to test.
    """
    for stream in _streams(small_pdf):
        runs = _runs(stream.data)
        body = runs[1 : 1 + gen.PARAGRAPHS_PER_PAGE * gen.LINES_PER_PARAGRAPH]
        assert all(run.size == gen.BODY_SIZE_PT for run in body)

        assert runs[0].size == gen.HEADING_SIZE_PT
        assert runs[0].y - body[0].y > gen.LEADING_PT + EPS

        for paragraph in range(gen.PARAGRAPHS_PER_PAGE):
            first = paragraph * gen.LINES_PER_PARAGRAPH
            for line in range(1, gen.LINES_PER_PARAGRAPH):
                drop = body[first + line - 1].y - body[first + line].y
                assert abs(drop - gen.LEADING_PT) < EPS
            if paragraph + 1 < gen.PARAGRAPHS_PER_PAGE:
                boundary = body[first + gen.LINES_PER_PARAGRAPH - 1].y
                nxt = body[first + gen.LINES_PER_PARAGRAPH].y
                assert boundary - nxt > gen.LEADING_PT + EPS

        cells = runs[1 + len(body) :]
        assert body[-1].y - cells[0].y > gen.LEADING_PT + EPS


def test_the_table_is_nine_rows_of_six_cells_in_row_major_order(small_pdf: bytes) -> None:
    """The cells are the reason this fixture measures the number 07-store-and-retrieval.md:1012
    is talking about, so their shape is asserted rather than assumed: a constant y across a row,
    a strictly-greater-than-leading step between rows, a monotone x within a row, and text in the
    ten-character class a table cell occupies."""
    for stream in _streams(small_pdf):
        cells = _runs(stream.data)[1 + gen.PARAGRAPHS_PER_PAGE * gen.LINES_PER_PARAGRAPH :]
        assert len(cells) == gen.TABLE_ROWS * gen.TABLE_COLS
        assert all(cell.size == gen.CELL_SIZE_PT for cell in cells)
        for row in range(gen.TABLE_ROWS):
            in_row = cells[row * gen.TABLE_COLS : (row + 1) * gen.TABLE_COLS]
            assert all(abs(cell.y - in_row[0].y) < EPS for cell in in_row)
            xs = [cell.x for cell in in_row]
            assert xs == sorted(xs)
            assert all(len(cell.text) <= 10 for cell in in_row)
            if row:
                previous = cells[(row - 1) * gen.TABLE_COLS].y
                assert previous - in_row[0].y > gen.LEADING_PT + EPS


def test_a_body_run_is_about_seventy_five_ascii_characters(small_pdf: bytes) -> None:
    """ "~75 characters" made checkable: never over the bound, never so far under it that a
    paragraph stops resembling ~300 B of prose (07-store-and-retrieval.md:1012)."""
    for stream in _streams(small_pdf):
        body = _runs(stream.data)[1 : 1 + gen.PARAGRAPHS_PER_PAGE * gen.LINES_PER_PARAGRAPH]
        for run in body:
            assert run.text.isascii()
            assert 60 <= len(run.text) <= gen.BODY_CHARS


def test_only_the_backslash_and_the_two_parentheses_are_ever_escaped(small_pdf: bytes) -> None:
    """`_unescape` rejects an unknown escape and an unescaped parenthesis, so running it over
    every literal on every page IS the escaping assertion. What this adds is the other half: that
    escaped literals actually OCCUR, in both the prose branch and the cell branch. An escaping
    rule the corpus never exercises leaves the stub driver's `Quote.VERBATIM` /
    `Quote.NORMALIZED` distinction unproven, which is the rung the Quote ladder exists to hold."""
    escaped_prose = 0
    escaped_cells = 0
    for stream in _streams(small_pdf):
        runs = _runs(stream.data)
        body_end = 1 + gen.PARAGRAPHS_PER_PAGE * gen.LINES_PER_PARAGRAPH
        for index, run in enumerate(runs):
            if b"\\" not in run.literal:
                continue
            if index < body_end:
                escaped_prose += 1
            else:
                escaped_cells += 1
            assert len(run.literal) > len(run.text)
    assert escaped_prose > 0
    assert escaped_cells > 0


def test_the_blocks_per_page_the_constants_imply_sit_inside_the_plan_envelope() -> None:
    """64 blocks/page: 1 heading + 8 paragraphs + 1 table + 54 cells, page root excluded.

    **This is a property of the fixture, not a measurement of a corpus** (ruling D27). All that is
    asserted is that the fixture lands inside the plan's stated 60-120 blocks/page envelope
    (00-vision.md:474, 07-store-and-retrieval.md:1095), because a fixture outside the envelope
    would be measuring `store.bytes_per_block` over a page the plan is not describing. F1's
    blocks-per-page half closes in P3 against ten real 200-page documents
    (03-document-model.md:3086) and nothing here anticipates that number.
    """
    assert gen.BLOCKS_PER_PAGE_FIXTURE == 64
    assert 60 <= gen.BLOCKS_PER_PAGE_FIXTURE <= 120


# ---------------------------------------------------------------------------------------------
# The regime: 13-quality.md:586-589
# ---------------------------------------------------------------------------------------------


class _NoClock(datetime.datetime):
    """`datetime.datetime` with its three clock constructors removed.

    A subclass rather than a patched attribute, because `datetime.datetime` is a C type and its
    methods cannot be assigned; replacing the name on the `datetime` MODULE is the only patch the
    interpreter allows, and it is the one every caller of `datetime.datetime.now()` goes through.
    The signatures swallow anything, so `now(tz=UTC)` raises exactly as `now()` does.
    """

    @classmethod
    def now(cls, *_args: object, **_kwargs: object) -> _NoClock:
        raise AssertionError("13-quality.md:586-589: a generator may not read datetime.now")

    @classmethod
    def utcnow(cls, *_args: object, **_kwargs: object) -> _NoClock:
        raise AssertionError("13-quality.md:586-589: a generator may not read the clock")

    @classmethod
    def today(cls, *_args: object, **_kwargs: object) -> _NoClock:
        raise AssertionError("13-quality.md:586-589: a generator may not read the clock")


_FORBIDDEN: Final = (
    # `random` and `secrets` are reached as `sys.modules[...]` rather than imported: ruff's
    # TID251 bans `import random` repository-wide ("Sampling is blake2b. Determinism is a gate,
    # not a habit.", pyproject.toml), and this file has no reason to take that escape.
    "random.random",
    "random.randint",
    "random.randrange",
    "random.choice",
    "random.choices",
    "random.shuffle",
    "random.sample",
    "random.uniform",
    "random.getrandbits",
    "random.seed",
    "secrets.token_bytes",
    "secrets.token_hex",
    "secrets.token_urlsafe",
    "secrets.randbelow",
    "secrets.choice",
    "uuid.uuid4",
    "time.time",
    "time.time_ns",
    "time.monotonic",
)


def _forbid_the_five_clocks(monkeypatch: pytest.MonkeyPatch) -> None:
    """Install 13-quality.md:586-589's harness: all five raise, and `SOURCE_DATE_EPOCH=0`."""

    def raiser(*_args: object, **_kwargs: object) -> object:
        raise AssertionError("13-quality.md:586-589: a generator may not sample or read a clock")

    for target in _FORBIDDEN:
        monkeypatch.setattr(target, raiser)
    monkeypatch.setattr("datetime.datetime", _NoClock)
    monkeypatch.setenv("SOURCE_DATE_EPOCH", "0")


def test_the_forbidden_clock_harness_actually_bites(monkeypatch: pytest.MonkeyPatch) -> None:
    """The harness before the tests that rely on it.

    A determinism test run under patches that silently failed to install would pass over a
    generator that reads the clock on every line, which is the most expensive way for this file
    to be useless. So each of the five is called here and each is required to raise.
    """
    _forbid_the_five_clocks(monkeypatch)
    with pytest.raises(AssertionError):
        sys.modules["random"].random()
    with pytest.raises(AssertionError):
        sys.modules["secrets"].token_bytes(4)
    with pytest.raises(AssertionError):
        sys.modules["uuid"].uuid4()
    with pytest.raises(AssertionError):
        sys.modules["time"].time()
    with pytest.raises(AssertionError):
        sys.modules["datetime"].datetime.now()


def test_the_generator_runs_under_the_five_patches_and_is_byte_identical(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """13-quality.md:586-589, run rather than read.

    The unpatched output is taken first, then the same page count is generated with `random`,
    `secrets`, `uuid4`, `time.time` and `datetime.now` all raising. Equal bytes prove two things
    at once: the generator touches none of the five, and its output does not depend on anything
    the patches would have perturbed.
    """
    plain = gen.generate(tmp_path / "plain.pdf", pages=SMALL_PAGES).read_bytes()
    _forbid_the_five_clocks(monkeypatch)
    patched = gen.generate(tmp_path / "patched.pdf", pages=SMALL_PAGES).read_bytes()
    assert patched == plain


def test_the_generator_names_none_of_the_five_anywhere_it_could_execute() -> None:
    """A static companion to the runtime patches, over the AST rather than over the text.

    The module DOCSTRING quotes 13-quality.md:586-589 and therefore contains all five names, so a
    grep would fail on a file that is perfectly compliant -- a comment is not a definition site.
    Walking the AST asks the only question that matters: is any of the five ever imported, named
    or reached as an attribute in code that runs?
    """
    tree = ast.parse(GEN_PATH.read_text(encoding="utf-8"))
    banned = {"random", "secrets", "uuid4", "uuid", "time", "datetime"}
    seen: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            seen.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            seen.add(node.module.split(".")[0])
            seen.update(alias.name for alias in node.names)
        elif isinstance(node, ast.Name):
            seen.add(node.id)
        elif isinstance(node, ast.Attribute):
            seen.add(node.attr)
    assert banned.isdisjoint(seen), f"forbidden names reachable in code: {sorted(banned & seen)}"


def test_two_runs_of_the_same_page_count_are_byte_identical(tmp_path: Path) -> None:
    """The weakest determinism claim, and the one a broken dict ordering would break first."""
    first = gen.generate(tmp_path / "a.pdf", pages=SMALL_PAGES).read_bytes()
    second = gen.generate(tmp_path / "b.pdf", pages=SMALL_PAGES).read_bytes()
    assert first == second


def test_the_content_of_a_page_does_not_depend_on_the_page_count(tmp_path: Path) -> None:
    """ "The content of page `i` is a pure function of `i`" (the frozen contract), checked where
    it bites: the content streams of an eight-page run must be the first eight content streams of
    a twenty-page run, byte for byte. Without this the small pin in `EXPECTED.sha256` would say
    nothing at all about the 5,000-page corpus it stands in for."""
    small = gen.generate(tmp_path / "small.pdf", pages=SMALL_PAGES).read_bytes()
    large = gen.generate(tmp_path / "large.pdf", pages=20).read_bytes()
    small_streams = [stream.data for stream in _streams(small)]
    large_streams = [stream.data for stream in _streams(large)]
    assert small_streams == large_streams[:SMALL_PAGES]


def test_the_output_directory_is_gitignored() -> None:
    """13-quality.md:588 requires `fixtures/generated/` to be `.gitignore`d, and `default_out`
    puts every output there. Both halves are asserted, because either one alone permits a 29 MB
    corpus in a pull request."""
    assert gen.default_out(5_000) == REPO_ROOT / "fixtures" / "generated" / "gen_5000p.pdf"
    patterns = {
        line.strip()
        for line in GITIGNORE.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    }
    assert "fixtures/generated/" in patterns


# ---------------------------------------------------------------------------------------------
# EXPECTED.sha256 -- the pins
# ---------------------------------------------------------------------------------------------


def _pins() -> dict[str, str]:
    """`EXPECTED.sha256` as `{path: digest}`, in the standard `sha256sum` format."""
    pins: dict[str, str] = {}
    for line in EXPECTED_PATH.read_text(encoding="utf-8").splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        digest, _, path = line.partition("  ")
        assert re.fullmatch(r"[0-9a-f]{64}", digest), f"not a sha256: {line!r}"
        assert path, f"no path on pin line: {line!r}"
        pins[path] = digest
    return pins


def test_the_pin_file_names_both_outputs_in_sha256sum_format() -> None:
    """Two lines, the small one and the default one, each `hash  path` with the path relative to
    the workspace root so `sha256sum -c fixtures/gen/EXPECTED.sha256` works from there."""
    pins = _pins()
    assert set(pins) == {
        f"fixtures/generated/gen_{SMALL_PAGES}p.pdf",
        f"fixtures/generated/gen_{gen.DEFAULT_PAGES}p.pdf",
    }


def test_the_small_pin_is_the_digest_of_a_freshly_generated_eight_page_run(tmp_path: Path) -> None:
    """The cheap half of 13-quality.md:588, in about a tenth of a second.

    The expected digest is a literal in a committed file the generator never reads, so this
    comparison pins a VALUE and not merely an agreement between two things that move together.
    """
    out = gen.generate(tmp_path / f"gen_{SMALL_PAGES}p.pdf", pages=SMALL_PAGES)
    digest = hashlib.sha256(out.read_bytes()).hexdigest()
    assert digest == _pins()[f"fixtures/generated/gen_{SMALL_PAGES}p.pdf"]


def test_the_default_pin_is_the_digest_of_a_freshly_generated_five_thousand_page_run(
    tmp_path: Path,
) -> None:
    """The expensive half: ~29 MB and ~1.2 s.

    It is run anyway. 13-quality.md:588 wants a generator change to be "a one-line visible diff
    rather than a silent corpus change", and a pin nothing checks is a line that can go stale
    without anyone noticing -- which is the silent corpus change, arriving by the front door. The
    eight-page pin exists so that a developer can check the regime without this run, not so that
    this run never happens.
    """
    out = gen.generate(tmp_path / f"gen_{gen.DEFAULT_PAGES}p.pdf", pages=gen.DEFAULT_PAGES)
    assert gen.sha256_of(out) == _pins()[f"fixtures/generated/gen_{gen.DEFAULT_PAGES}p.pdf"]


# ---------------------------------------------------------------------------------------------
# The command line
# ---------------------------------------------------------------------------------------------


def test_main_reports_the_path_the_size_the_digest_and_the_page_count(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    out = tmp_path / "cli.pdf"
    code = gen.main(["--pages", "2", "--out", str(out)])
    assert code == 0
    report = capsys.readouterr().out
    assert f"path    {out}" in report
    assert f"bytes   {out.stat().st_size}" in report
    assert f"sha256  {gen.sha256_of(out)}" in report
    assert "pages   2" in report


def test_print_sha256_emits_one_line_in_the_format_the_pin_file_wants(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The flag exists so that a regenerated fixture's pin line can be pasted, not retyped."""
    out = tmp_path / "cli.pdf"
    assert gen.main(["--pages", "2", "--out", str(out), "--print-sha256"]) == 0
    last = capsys.readouterr().out.strip().splitlines()[-1]
    digest, separator, path = last.partition("  ")
    assert separator == "  "
    assert digest == gen.sha256_of(out)
    assert path == out.name


def test_a_page_count_below_one_is_refused_by_both_the_library_and_the_command(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Exit 2, and no file written. Zero pages would produce a `/Pages` node with an empty
    `/Kids`, which is a PDF no reader accepts and a fixture no test could use."""
    with pytest.raises(ValueError, match="pages must be >= 1"):
        gen.generate(tmp_path / "none.pdf", pages=0)
    assert gen.main(["--pages", "0", "--out", str(tmp_path / "none.pdf")]) == 2
    assert "must be >= 1" in capsys.readouterr().err
    assert not (tmp_path / "none.pdf").exists()


# ---------------------------------------------------------------------------------------------
# The VALUES, pinned as literals
# ---------------------------------------------------------------------------------------------
#
# Everything above this line asserts a RELATION -- that the emitted bytes agree with the
# constants that produced them. An adversarial pass (P2 stage C) mutated the generator twenty-one
# ways and found that nine of those mutations changed the corpus without failing a single
# relation: only the two `EXPECTED.sha256` pins went red, and `fixtures/gen/README.md` tells the
# developer who sees a red pin to regenerate and re-pin. Re-pinning was then applied to each of
# the nine and the whole file went green again.
#
#   `LEADING_PT` 12.0 -> 12.5                      the coalescing predicate drifts
#   `HEADING_SIZE_PT` 18.0 -> 10.0                 the heading becomes indistinguishable
#   `TABLE_ROWS`/`TABLE_COLS` 9x6 -> 6x9           the table transposes, cells leave the page
#   `TABLE_COL_W_PT` 80.0 -> 140.0                 the columns leave the page
#   `BODY_CHARS` 75 -> 150                         a paragraph stops being ~300 B of prose
#   `WORD_STEP` 7919 -> 64                         every word in a line becomes the same word
#   the last `/Kids` entry dropped, `/Count` kept  the page tree stops naming a page
#   `_file_id` stops depending on `pages`          two different documents share an `/ID`
#   `body_text(page)` -> `body_text(page + 1)`     page i carries page i+1's prose
#   the word arithmetic shifted by one page        every page's prose changes together
#
# The cause in six of those is rule 5 of this session's house rules: WHEN BOTH SIDES OF AN
# EQUALITY COME FROM THE SAME STORE, THE TEST PINS AGREEMENT AND NOT VALUE. A test that reads
# `gen.LEADING_PT` and compares it to a gap the generator computed FROM `gen.LEADING_PT` moves
# with the constant and can never report that the constant moved. That matters here beyond
# tidiness: `tools/p2_stub_parse.py` transcribes these same numbers as its own literals
# (`_HEADING_SIZE_PT = 18.0`, `_BODY_SIZE_PT = 10.0`, `_CELL_SIZE_PT = 8.0` at :172-174 and
# `_LEADING_PT = 12.0` at :176) and classifies every run by them, so a silent drift on this side
# breaks the P2 demo (16-roadmap.md:442) at a distance and no test in either file would say so.
#
# The tests below therefore pin VALUES, as literals typed here, against bytes read out of a
# freshly generated file. Neither side is `gen`.
#
# The other three of the nine are not rule-5 shaped: they are parts of the file no test looked at
# at all -- the page tree, the `/ID`, and the page-to-content wiring. Two further mutations
# survived even the hash pins, because they hit code no test executes: `generate`'s `mkdir` and
# the workspace-relative branch of `--print-sha256`.

BACKSLASH: Final = chr(92)
"""One backslash, written without one.

The generator plants a parenthesised, backslash-bearing token at the head of every third
paragraph precisely so the escape path is exercised, and one of the pins below quotes that token
verbatim. Spelling the character as `chr(92)` keeps the pinned string unambiguous: a doubled
backslash inside a string literal is the one thing in a pin that a reader, a diff or a
copy-and-paste can silently halve, and a pin that is quietly wrong is worse than no pin at all.
"""

HEADING_PT: Final = 18.0
BODY_PT: Final = 10.0
CELL_PT: Final = 8.0
LEADING: Final = 12.0
HEADING_GAP: Final = 24.0
PARAGRAPH_GAP: Final = 18.0
TABLE_GAP: Final = 24.0
ROW_PITCH: Final = 14.0
COL_PITCH: Final = 80.0
LEFT_MARGIN: Final = 56.693
RIGHTMOST_BASELINE: Final = 456.693
TOP_BASELINE: Final = 785.197
PAGE_W: Final = 595.276
PAGE_H: Final = 841.890
"""The frozen geometry, as literals rather than as `gen.X`.

Every size and the leading is also a literal in `tools/p2_stub_parse.py` (:172-176), which is the
point: two independent transcriptions of one contract, and a test that fails the moment the
generator's side of it moves.
"""

FIRST_BODY_RUN: Final = 1
FIRST_CELL_RUN: Final = 33
RUNS_ON_A_PAGE: Final = 87
"""Run indices within a page, as literals: run 0 is the heading, runs 1-32 are the thirty-two body
lines (eight paragraphs of four), runs 33-86 are the fifty-four cells (nine rows of six)."""


def _pages(data: bytes) -> list[list[Run]]:
    """Every page's runs, in page order."""
    return [_runs(stream.data) for stream in _streams(data)]


def test_the_three_text_sizes_are_the_distinct_literals_the_stub_driver_transcribes(
    small_pdf: bytes,
) -> None:
    """18/10/8 point, and no two of them equal.

    `test_the_three_font_sizes_appear_once_each_per_page_and_in_emission_order` above compares
    the emitted sizes to `gen.HEADING_SIZE_PT`, `gen.BODY_SIZE_PT` and `gen.CELL_SIZE_PT`, so
    setting `HEADING_SIZE_PT = 10.0` leaves it green: the generator then writes `/F1 10.000 Tf`
    twice and the test's expectation has moved to `[10.0, 10.0, 8.0]` with it. The corpus that
    results has no distinguishable heading, and `tools/p2_stub_parse.py:867` -- which finds the
    heading with `_is_size(run, _HEADING_SIZE_PT)` against its own literal 18.0 -- would find
    thirty-three of them on every page. DISTINCTNESS is the property the stub depends on, it is
    implied by no relation, and so it is asserted here together with the values.
    """
    assert (gen.HEADING_SIZE_PT, gen.BODY_SIZE_PT, gen.CELL_SIZE_PT) == (18.0, 10.0, 8.0)
    assert len({HEADING_PT, BODY_PT, CELL_PT}) == 3
    for page in _pages(small_pdf):
        assert page[0].size == HEADING_PT
        assert {run.size for run in page[FIRST_BODY_RUN:FIRST_CELL_RUN]} == {BODY_PT}
        assert {run.size for run in page[FIRST_CELL_RUN:]} == {CELL_PT}


def test_the_leading_is_the_frozen_twelve_points_and_every_other_gap_is_its_own_literal(
    small_pdf: bytes,
) -> None:
    """Each vertical step in the page, pinned to the number the contract fixes it at.

    `test_a_paragraph_drops_by_exactly_the_leading_and_every_other_gap_is_larger` above asserts
    `abs(drop - gen.LEADING_PT) < EPS` and `gap > gen.LEADING_PT + EPS`. Both sides of the first
    comparison come out of `gen`, so `LEADING_PT = 12.5` leaves it green -- the generator steps
    by 12.5, the test expects 12.5, and the only thing that changed is that
    `tools/p2_stub_parse.py:176`'s independent `_LEADING_PT = 12.0` stops coalescing anything,
    turning every paragraph in the P2 demo into four one-line paragraphs. The relation is worth
    keeping; what it cannot do is notice that the value moved.
    """
    assert gen.LEADING_PT == LEADING
    for page in _pages(small_pdf):
        assert abs(page[0].y - TOP_BASELINE) < EPS
        body = page[FIRST_BODY_RUN:FIRST_CELL_RUN]
        assert abs((page[0].y - body[0].y) - HEADING_GAP) < EPS
        for paragraph in range(8):
            first = paragraph * 4
            for line in range(1, 4):
                assert abs((body[first + line - 1].y - body[first + line].y) - LEADING) < EPS
            if paragraph < 7:
                gap = body[first + 3].y - body[first + 4].y
                assert abs(gap - PARAGRAPH_GAP) < EPS
        cells = page[FIRST_CELL_RUN:]
        assert abs((body[-1].y - cells[0].y) - TABLE_GAP) < EPS
        for row in range(1, 9):
            pitch = cells[(row - 1) * 6].y - cells[row * 6].y
            assert abs(pitch - ROW_PITCH) < EPS


def test_the_table_is_the_nine_rows_of_six_columns_the_contract_names(small_pdf: bytes) -> None:
    """9 x 6, and not 6 x 9.

    `RUNS_PER_PAGE` and `BLOCKS_PER_PAGE_FIXTURE` are both symmetric in the two constants, so a
    transposed table keeps 87 runs and 64 blocks and every test above stays green -- while nine
    columns at an 80 pt pitch put the last cell at x = 696.693, off the right edge of a page
    595.276 pt wide. The shape is the claim, so the shape is pinned.
    """
    assert (gen.TABLE_ROWS, gen.TABLE_COLS) == (9, 6)
    for page in _pages(small_pdf):
        cells = page[FIRST_CELL_RUN:]
        assert len(cells) == 54
        rows = sorted({round(cell.y, 3) for cell in cells}, reverse=True)
        columns = sorted({round(cell.x, 3) for cell in cells})
        assert len(rows) == 9
        assert len(columns) == 6
        for index, cell in enumerate(cells):
            assert abs(cell.y - rows[index // 6]) < EPS
            assert abs(cell.x - columns[index % 6]) < EPS
        assert all(
            abs((columns[i + 1] - columns[i]) - COL_PITCH) < EPS for i in range(len(columns) - 1)
        )


def test_no_run_is_placed_outside_the_media_box(small_pdf: bytes) -> None:
    """Every baseline inside `[0 0 595.276 841.890]`, and the last column inside the margin.

    Widening `TABLE_COL_W_PT` to 140.0, or transposing the table, marches the right-hand cells
    off the page. Nothing above looks at where a run actually lands -- the table test asserts
    only that x increases along a row -- so a corpus whose right-hand third sits outside the page
    box would ship, and `store.bytes_per_block` would be measured over a page no reader renders.
    `MARGIN_LEFT_PT + 5 * TABLE_COL_W_PT = 456.693` is the rightmost baseline the contract allows
    and it is pinned as that literal.
    """
    for page in _pages(small_pdf):
        assert abs(min(run.x for run in page) - LEFT_MARGIN) < EPS
        assert abs(max(run.x for run in page) - RIGHTMOST_BASELINE) < EPS
        for run in page:
            assert LEFT_MARGIN - EPS <= run.x <= PAGE_W - LEFT_MARGIN + EPS
            assert 0.0 < run.y < PAGE_H


def test_a_body_run_is_bounded_by_the_seventy_five_characters_the_contract_names(
    small_pdf: bytes,
) -> None:
    """75, as a literal, and no run that is one word repeated.

    `test_a_body_run_is_about_seventy_five_ascii_characters` above bounds the run by
    `gen.BODY_CHARS`, so doubling that constant to 150 leaves it green while every paragraph
    stops being the ~300 B of prose 07-store-and-retrieval.md:1012 makes the dominant term of
    `store.bytes_per_block`. The second half of this test covers the other way the same sentence
    can go wrong: `WORD_STEP` is documented as "a prime stride through `WORDS`, so consecutive
    words in a line differ", and at `WORD_STEP = 64` -- the pool size -- every word in a line is
    the same word, which is 75 characters of something that is not prose.
    """
    assert gen.BODY_CHARS == 75
    for page in _pages(small_pdf):
        for run in page[FIRST_BODY_RUN:FIRST_CELL_RUN]:
            assert run.text.isascii()
            assert 60 <= len(run.text) <= 75
            words = run.text.split(" ")
            assert len(words) >= 6
            assert len(set(words)) == len(words)


def test_the_page_tree_names_every_page_object_exactly_once_and_counts_them_all(
    small_pdf: bytes,
) -> None:
    """`/Count` and `/Kids` against the page objects that are actually in the file.

    Dropping the last entry from `/Kids` while leaving `/Count` alone produces a file whose every
    other property is intact: 87 runs per stream, twenty objects, every xref offset correct,
    eight `/MediaBox` lines, eight content streams. Nothing above parses the page tree, so the
    whole suite stayed green on it and only the two hash pins moved. A reader that walks `/Kids`
    -- which is what a reader does -- would show seven pages of a document the store believes has
    eight.
    """
    tree = re.search(rb"/Type /Pages /Count (\d+) /Kids \[([^\]]*)\]", small_pdf)
    assert tree is not None, "no /Pages node in the file"
    kids = [int(number) for number in re.findall(rb"(\d+) 0 R", tree.group(2))]
    assert int(tree.group(1)) == SMALL_PAGES
    assert kids == [5 + 2 * (page - 1) for page in range(1, SMALL_PAGES + 1)]

    written = [
        int(number)
        for number in re.findall(rb"^(\d+) 0 obj\n<< /Type /Page /Parent ", small_pdf, re.MULTILINE)
    ]
    assert written == kids


def test_every_run_on_a_page_is_the_pure_function_evaluated_at_that_pages_own_number(
    small_pdf: bytes,
) -> None:
    """The WIRING: page `p`'s bytes come from `heading_text(p)`, `body_text(p, ...)` and
    `cell_text(p, ...)`, never from `p + 1`.

    `test_the_content_of_a_page_does_not_depend_on_the_page_count` above cannot see an off-by-one
    here, because the same off-by-one applies at both page counts and the two prefixes still
    match. This test compares each page's emitted runs to the pure functions evaluated at that
    page's own ordinal, taken from its POSITION in the file, so a page that carries its
    neighbour's prose fails. The functions themselves are pinned by literal in the test below;
    this one pins only that they are called with the right page.
    """
    for index, page in enumerate(_pages(small_pdf), start=1):
        assert len(page) == RUNS_ON_A_PAGE
        assert page[0].text == gen.heading_text(index)
        assert page[0].text.startswith(f"Article {index}. ")
        for offset, run in enumerate(page[FIRST_BODY_RUN:FIRST_CELL_RUN]):
            assert run.text == gen.body_text(index, offset // 4, offset % 4)
        for offset, run in enumerate(page[FIRST_CELL_RUN:]):
            assert run.text == gen.cell_text(index, offset // 6, offset % 6)


def test_the_words_a_page_carries_are_the_literals_this_test_pins(small_pdf: bytes) -> None:
    """The VALUES: seven runs, quoted here, read back out of the generated file.

    Shifting the word arithmetic by one page -- `seed = (page + 1) * PAGE_MIX` inside
    `heading_text` -- changes every page's text together, so no relation notices: the emitted
    heading still equals `gen.heading_text(page)`, the prefix is still `Article 1. `, the length
    is still in range. Only a literal can hold that, and only a literal survives the re-pin that
    `fixtures/gen/README.md` tells a developer to perform when a hash test fails.

    Seven pins, chosen to cover each generator branch once: a heading at each end of the run, an
    unescaped body line, the escaped body line the every-third-paragraph rule plants, an ordinary
    cell and the parenthesised cell `ESCAPED_CELL_PAGE_STRIDE` puts on page 5. The last of them
    also pins the table's shape: a transposed table has no `R8C5` cell at all.
    """
    pages = _pages(small_pdf)
    assert pages[0][0].text == "Article 1. Schedule and severance"
    assert pages[7][0].text == "Article 8. Representation and consent"
    assert pages[0][FIRST_BODY_RUN].text == (
        "schedule severance inspection counterpart custody effective escalation"
    )
    assert pages[1][FIRST_BODY_RUN + 5].text == (
        f"(see {BACKSLASH} clause) clause survival acceptance novation escrow annual renewal"
    )
    assert pages[0][FIRST_CELL_RUN].text == "R0C0-0031"
    assert pages[4][FIRST_CELL_RUN + 4 * 6 + 2].text == "R4C2(0185)"
    assert pages[7][FIRST_CELL_RUN + 8 * 6 + 5].text == "R8C5-0309"


def test_the_file_id_is_thirty_two_hex_digits_that_move_when_the_document_moves(
    small_pdf: bytes, tmp_path: Path
) -> None:
    """`/ID [<x> <x>]`, and two different documents do not share an `x`.

    A PDF `/ID` is conventionally random and 13-quality.md:586-589 forbids random, so `_file_id`
    digests the one input that changes the file. Its docstring claims the substitute "still
    differs between two files that differ"; nothing checked that, and replacing the digest with a
    constant left every test green. An `/ID` shared by two different documents is the one
    property of an `/ID` that is load-bearing, so it is the one asserted.
    """
    pattern = re.compile(rb"/ID \[<([0-9A-F]{32})> <([0-9A-F]{32})>\]")
    small = pattern.search(small_pdf)
    assert small is not None, "no /ID in the trailer"
    assert small.group(1) == small.group(2)

    other = gen.generate(tmp_path / "twenty.pdf", pages=20).read_bytes()
    large = pattern.search(other)
    assert large is not None
    assert large.group(1) != small.group(1)


def test_generate_creates_an_output_directory_that_does_not_exist_yet(tmp_path: Path) -> None:
    """`fixtures/generated/` is `.gitignore`d, so on a fresh clone it is NOT THERE.

    `generate` calls `out.parent.mkdir(parents=True, exist_ok=True)` for exactly that reason, and
    deleting that line left the whole suite green -- every other test writes into a `tmp_path`
    pytest has already created, so the line was never executed by anything. The first person to
    run `uv run python fixtures/gen/gen_5000p_pdf.py` on a clean checkout would have got a
    `FileNotFoundError` from the README's first example. The absent directory is the point of
    this test: state the run has to create, not state it finds already there.
    """
    target = tmp_path / "fixtures" / "generated" / "gen_1p.pdf"
    assert not target.parent.exists()
    assert gen.generate(target, pages=1) == target
    assert target.read_bytes().startswith(b"%PDF-1.4\n")


def test_print_sha256_names_the_output_relative_to_the_workspace_root(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The branch the flag exists for, which no test reached.

    `--print-sha256` emits `digest  <path relative to the workspace root>` so the line can be
    pasted into `EXPECTED.sha256`, and falls back to the bare filename when the output lies
    outside the workspace. `test_print_sha256_emits_one_line_in_the_format_the_pin_file_wants`
    writes into `tmp_path`, which is outside the workspace, so it only ever exercised the
    FALLBACK: corrupting the relative path left it green. Here `repo_root` is pointed at a
    temporary workspace so the real branch runs, and the emitted path is checked against the
    literal `EXPECTED.sha256` wants.
    """
    monkeypatch.setattr(gen, "repo_root", lambda: tmp_path)
    out = tmp_path / "fixtures" / "generated" / "gen_2p.pdf"
    assert gen.main(["--pages", "2", "--out", str(out), "--print-sha256"]) == 0
    last = capsys.readouterr().out.strip().splitlines()[-1]
    digest, separator, path = last.partition("  ")
    assert separator == "  "
    assert digest == gen.sha256_of(out)
    assert path == "fixtures/generated/gen_2p.pdf"
