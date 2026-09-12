"""The testkit's engine: a `BlobStore`, a `DriverIO`, a fixture, and the fragment read back.

04-driver-system.md:2064 gives `omniweave-conform` "the driver **testkit** (~120 property tests,
which the `read_back` drivers run unchanged)". A property test needs something to run the driver
*in*, and this module is that something. Nine of the twelve suites call `run_parse()`; none of them
builds a `DriverIO` of its own.

## Why this is not `GuardIO`, and the distinction is not a technicality

`omniweave_core.host.inproc.GuardIO` is the `DriverIO` the *host* hands an `inproc` driver, and the
kit cannot use it -- not because it is inconvenient but because the kit is not the host:

* `DriverGuard.__init__` requires a `Candidate`, which only `resolve()` builds and only after
  nineteen gates. The kit runs a driver that no `Requirement` asked for.
* `DriverGuard` refuses to run anything it did not grant `Isolation.INPROC`, and DR9's six
  conjuncts make `inproc` **unreachable for a third party by construction**
  (04-driver-system.md:2126). Every card the kit is pointed at is a third party's.

So the two are not two implementations of one thing (INV-21): `GuardIO` enforces three deadlines on
a call the router chose, and `KitIO` is an instrument that drives a call *nobody* chose, with the
cancellation under the suite's control rather than under a watchdog's. What they share is the
`DriverIO` contract, which is `omniweave_ports`' and is declared exactly once.

**What `KitIO` therefore does not do, and which suite covers it instead.** It enforces no wall
clock, no `progress_ms` and no memory ceiling. Those are the host's, they are enforced across S4,
and the `limits` suite checks them against the real host rather than against this double -- which is
the correct place, because 04-driver-system.md:2078 makes the distinction itself: "every
driver-enforced `[limits]` value refuses at the read boundary ... and every host-enforced one
refuses **before** `INVOKE`".

## The fragment reader

A `parse/1` driver returns `owdoc-fragment/1`: one JSON record per line, `t` naming the kind.
`read_fragment()` decodes it into `Fragment`, which is the only thing the `capability` suite reads.
It validates the framing and nothing else -- a record with an unknown `t` is kept and counted, not
refused, because deciding what a driver may emit is `omniweave/run/dispatch.py`'s job and a kit that
re-implemented the decision would be a second grammar for the wire.

Specified in 04-driver-system.md section 8.2 and 18-api-sketch.md section 5.2.
"""

from __future__ import annotations

import hashlib
import io as _io
import json
import threading
import tomllib
import unicodedata
import weakref
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any, BinaryIO, Final

from omniweave_core.errors import CapabilityMissing
from omniweave_ports.types import DriverIO, Scalar

if TYPE_CHECKING:
    from collections.abc import Iterator, Mapping, Sequence

    from omniweave_ports.types import ArtifactRef, DriverResult, ServiceHandle

__all__ = [
    "DEFAULT_DEADLINE_MS",
    "DEFAULT_MAX_OUTPUT_BYTES",
    "NOT_INPUTS",
    "ORIGIN_VERIFIER",
    "Call",
    "Fixture",
    "Fragment",
    "KitIO",
    "MemoryBlobStore",
    "OriginCheck",
    "load_fixtures",
    "make_io",
    "read_fragment",
    "reverify_origin",
    "run_parse",
]


DEFAULT_MAX_OUTPUT_BYTES: Final = 33_554_432
"""32 MiB. The template card's `max_input_bytes`, mirrored as an output ceiling for a run the kit
drives. Not a plan constant and not pretending to be one: a real invocation's ceiling comes from
`omniweave_core.limits.effective()`, which takes a three-way minimum the kit has no run to read.
`make_io(max_output_bytes=...)` is how the `limits` suite lowers it to a value it can cross."""

DEFAULT_DEADLINE_MS: Final = 60_000
"""One minute. `KitIO` does not enforce it -- see the module docstring -- and carries it because
`DriverIO` has the field and a driver may read it to size its own work."""

ORIGIN_VERIFIER: Final = "verify_origin"
"""The optional method a driver ships so P7 can be proved on a branch only it can read.

    verify_origin(part: bytes, origin: Mapping[str, Any], text: str) -> tuple[bool, str]

Returns `(ok, reason)`; `reason` is empty when `ok` and otherwise says WHY, so a verifier can tell
"the address does not resolve here" from "the text differs".

**Why this exists.** 03-document-model.md:2991 requires P7 on **all three** of INV-10's branches.
The `bytes` branch is self-contained -- decode a slice of the part -- and the kit proves it
unaided. The other two are not: `nodepath` needs a reader for the part's own container format, and
`glyphs` needs the recorded `os_extractor` re-run, which for `parse.pdf.pdfium` means pdfium. The
plan requires the assertion and supplies no mechanism for making it, so the kit names one: a method
on the driver class the kit already activated.

It is OPTIONAL and the absence is not a pass. A driver without it gets an honest "not re-verified"
-- and that is still a failing assertion for a card claiming `exact`, because an unproved claim is
what P7 exists to catch.

**The hook cannot make a false claim true.** It is handed the retained part and the block's own
recorded address, and the caller compares its answer against the block's text. A driver that
returned `(True, "")` unconditionally would pass here -- and would also face a `bytes`-branch
fixture the kit checks itself, so the cheapest defence against that is the one already here: the
kit proves `bytes` without asking.

**It lives in this module and not in the `capability` suite** because `reverify_origin()` below is
the one home of the three-branch decision, and two callers reach it: P7, which asks it of every
body block when the CARD declares `origin_span = "exact"`, and `evaluate.span_exact_rate`, which
asks it of every block whose own `quote` claims `verbatim`. A constant named in one suite and read
by another module is the shape INV-21 asks you to notice.
"""

_CAS: Final = "cas://"
_SHA_HEX_LEN: Final = 64


class MemoryBlobStore:
    """The CAS as a driver sees it, backed by a dict and one real directory.

    `path()` must return "a READ-ONLY filesystem path under `roots.source_ro`"
    (`omniweave_ports.types.BlobStore`), and a path has to exist for a driver that opens it by
    name, so this writes each blob once into the directory it was given. The dict is what `open()`
    and `head()` read, so a driver that never touches `path()` never pays for the file.

    `put()` is here rather than metered here: the ceiling is `ArtifactRef.of`'s, "enforced HERE,
    ONCE" (`types.py:405-411`), and a second check in the store would be the second implementation
    of a safety limit the plan names as the failure mode.
    """

    def __init__(self, root: Path) -> None:
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)
        self._blobs: dict[str, bytes] = {}
        self.puts: list[str] = []

    @staticmethod
    def digest_of(data: bytes) -> str:
        return hashlib.sha256(data).hexdigest()

    @staticmethod
    def _bare(digest: str) -> str:
        return digest[len(_CAS) :] if digest.startswith(_CAS) else digest

    def add(self, data: bytes) -> str:
        """Seed a blob the driver will be asked to read. Returns the bare hex digest."""
        digest = self.digest_of(data)
        self._blobs[digest] = data
        return digest

    def path(self, digest: str) -> str:
        bare = self._bare(digest)
        if bare not in self._blobs:
            msg = f"no blob {bare!r} in this store"
            raise KeyError(msg)
        target = self.root / bare
        if not target.exists():
            target.write_bytes(self._blobs[bare])
        return str(target)

    def open(self, digest: str) -> BinaryIO:
        bare = self._bare(digest)
        if bare not in self._blobs:
            msg = f"no blob {bare!r} in this store"
            raise KeyError(msg)
        return _io.BytesIO(self._blobs[bare])

    def put(self, data: bytes) -> str:
        digest = self.add(data)
        self.puts.append(digest)
        return f"{_CAS}{digest}"

    def __contains__(self, digest: object) -> bool:
        return isinstance(digest, str) and self._bare(digest) in self._blobs


@dataclass(slots=True)
class Call:
    """Everything one invocation did that a suite can ask about afterwards.

    Mutable and side-tabled rather than carried on `KitIO`, for the reason `GuardIO` gives for the
    same shape: `DriverIO` is frozen with four fields, `dataclasses.fields()` answering four is
    INV-6's literal audit question (01-principles.md section 12 row 2), and a fifth field here
    would amend the charter to hold a counter.
    """

    logs: list[tuple[str, Mapping[str, Scalar]]] = field(default_factory=list)
    progress: list[tuple[int, int | None]] = field(default_factory=list)
    services: list[str] = field(default_factory=list)
    cancel_after_progress: int = 0
    cancelled_now: bool = False
    lock: threading.Lock = field(default_factory=threading.Lock)

    def should_cancel(self) -> bool:
        if self.cancelled_now:
            return True
        limit = self.cancel_after_progress
        return bool(limit) and len(self.progress) >= limit


_CALLS: weakref.WeakKeyDictionary[DriverIO, Call] = weakref.WeakKeyDictionary()
"""Per-`DriverIO` recording, keyed on identity and weak, exactly as `_OUTPUT_METER` is. A finished
invocation's record dies with the `DriverIO` it belonged to, which is why `DriverIO` carries
`weakref_slot=True`."""


class KitIO(DriverIO):
    """The `DriverIO` the conformance kit hands a driver. FOUR FIELDS, all inherited.

    `cancelled()` answers from the suite's script rather than from a clock, which is the whole
    reason this class exists: `determinism` and `idempotence` need two runs to differ in nothing,
    and a wall-clock cancellation would make them differ in something no card declares.
    """

    __slots__ = ()

    def call(self) -> Call:
        record = _CALLS.get(self)
        if record is None:
            record = Call()
            _CALLS[self] = record
        return record

    def service(self, name: str) -> ServiceHandle:
        """Refuse by naming what is missing, and RECORD the ask.

        The kit attaches no Services: a driver whose card says `services = []` and which then
        calls `service()` is over-reaching, and the `contract` suite reads `Call.services` to say
        so with the name in hand. `CapabilityMissing` rather than `NotImplementedError` because
        the refusal is the host's shape of refusal, and a driver's error handling should meet the
        same exception in the kit that it will meet in production.
        """
        self.call().services.append(name)
        raise CapabilityMissing(
            f"service({name!r}): the conformance kit attaches no Services",
            missing=(f"service:{name}",),
            fix="declare it in [hardware] services and run the driver under a host that has it",
        )

    def cancelled(self) -> bool:
        record = self.call()
        with record.lock:
            return record.should_cancel()

    def log(self, event: str, **fields: Scalar) -> None:
        """One structured record. **Does NOT reset progress** (04-driver-system.md:1735)."""
        record = self.call()
        with record.lock:
            record.logs.append((event, dict(fields)))

    def progress(self, done: int, total: int | None) -> None:
        record = self.call()
        with record.lock:
            record.progress.append((done, total))


def make_io(
    blobs: MemoryBlobStore,
    tmpdir: Path,
    *,
    deadline_ms: int = DEFAULT_DEADLINE_MS,
    max_output_bytes: int = DEFAULT_MAX_OUTPUT_BYTES,
    cancel_after_progress: int = 0,
) -> KitIO:
    """One `KitIO` plus its `Call` record, already wired.

    `cancel_after_progress = N` makes `cancelled()` return True once the driver has reported
    progress N times. That is how the `contract` suite proves a driver actually checks at every
    loop top, without a timer and therefore without a flake.
    """
    tmpdir.mkdir(parents=True, exist_ok=True)
    io_obj = KitIO(
        blobs=blobs,
        tmpdir=str(tmpdir),
        deadline_ms=deadline_ms,
        max_output_bytes=max_output_bytes,
    )
    record = io_obj.call()
    record.cancel_after_progress = cancel_after_progress
    return io_obj


@dataclass(frozen=True, slots=True)
class Fixture:
    """One input file, its bytes, and its digest. The unit a suite iterates over.

    `name` is what an `Assertion` puts in its `fixture` field, so it is the file's name and never
    its absolute path: 04-driver-system.md:2334 wants a message a reader can act on, and an
    absolute path from someone else's machine is not that.
    """

    path: Path
    data: bytes
    digest: str
    media_type: str | None = None
    """What the HOST would have routed on, read from the fixture's own `.meta.toml` sidecar.

    `UnitRef.media_type` exists because routing already decided the format before `INVOKE`, and a
    driver is entitled to use it: `parse.office.anydoc` needs it to tell a legacy BIFF workbook
    from an OOXML one and to name CSV at all, because CSV carries no signature and cannot be
    detected from content by anyone.

    Without it every fixture reached `parse()` as `media_type=None`, so a kit run was strictly
    harder than a real invocation -- and a driver that is correct under the host would fail here
    for a reason no host would ever produce. 13-quality.md section 4.4's `[fixture] media_type` is
    where the answer already lives, so this reads that rather than inventing a second channel."""

    @property
    def name(self) -> str:
        return self.path.name

    @property
    def byte_len(self) -> int:
        return len(self.data)

    @classmethod
    def of(cls, path: Path) -> Fixture:
        """Read the file, canonicalise its path, and read the sidecar if there is one.

        `resolve()` here is NOT the ambient-cwd input OUT14 bans and
        `omniweave-no-getcwd-in-library-code` flags. That rule's subject is "a path no caller
        declared and no test can vary" -- graphify #1774 writing its cache into the analysed tree.
        This path arrived as an argument; canonicalising an argument is not reading an ambient
        one. It is done because `UnitRef.uri` is a `file:` URI and `Path.as_uri()` refuses a
        relative path, so a fixture named on the command line as `fixtures/a.txt` would otherwise
        fail at the URI and not at anything a driver did.
        """
        data = path.read_bytes()
        return cls(
            path=path.resolve(),
            data=data,
            digest=MemoryBlobStore.digest_of(data),
            media_type=_sidecar_media_type(path),
        )


def _sidecar_media_type(path: Path) -> str | None:
    """`[fixture] media_type` from `<file>.meta.toml`, or `None` when there is no sidecar.

    A malformed or absent sidecar is `None` and never an exception. The sidecar is optional by
    design -- `packages/omniweave-pdf/fixtures/` has none and needs none, because a PDF's media
    type is decidable from its first five bytes -- so a kit that refused to run without one would
    make an optional file mandatory for every driver to satisfy one.
    """
    sidecar = path.with_name(path.name + ".meta.toml")
    if not sidecar.is_file():
        return None
    try:
        table = tomllib.loads(sidecar.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, tomllib.TOMLDecodeError):
        return None
    fixture = table.get("fixture")
    if not isinstance(fixture, dict):
        return None
    value = fixture.get("media_type")
    return value if isinstance(value, str) and value else None


NOT_INPUTS: Final = frozenset({"EXPECTED.sha256", "README.md", "NOTICE", "LICENSE"})
"""Files a fixture directory carries ABOUT itself, which are not fixtures.

`EXPECTED.sha256` is the generator's digest manifest and `README.md` is the corpus's own prose;
both are written by `fixtures/gen/`, both sit beside the fixtures, and neither is a document
anybody wants parsed. Before this set existed the kit fed them to every driver and recorded the
refusal: `parse.pdf.pdfium` reported `README.md (corrupt_input)` and `parse.office.anydoc` reported
`EXPECTED.sha256 (unsupported_format)`, which is noise in a refusal count that a reader is supposed
to be able to scan for a real refusal.

A named set rather than a pattern, and the same shape `gate_vendor.check_digests` uses for the
same reason: a fixture directory's bookkeeping is a short closed list, and a pattern broad enough
to catch it (`*.md`, `*.sha256`) would also catch a Markdown fixture, which is a document
`parse.text.builtin` is specified to parse."""


def load_fixtures(directory: Path) -> tuple[Fixture, ...]:
    """Every regular file under `directory`, sorted, minus the three kinds that are not inputs.

    `*.meta.toml` is 13-quality.md section 4.4's fixture manifest -- metadata *about* a fixture --
    a dotfile is the toolchain's, and `NOT_INPUTS` is the corpus's own bookkeeping. Feeding any of
    them to a driver would be feeding it this repository's paperwork and calling the result a parse
    failure.
    """
    if not directory.is_dir():
        return ()
    found = [
        path
        for path in sorted(directory.rglob("*"))
        if path.is_file()
        and not path.name.startswith(".")
        and not path.name.endswith(".meta.toml")
        and path.name not in NOT_INPUTS
    ]
    return tuple(Fixture.of(path) for path in found)


@dataclass(frozen=True, slots=True)
class Fragment:
    """A decoded `owdoc-fragment/1` body: the records, split by kind.

    `unknown` is kept rather than refused. What a driver may emit is the dispatcher's grammar and
    it has one home; a kit that re-decided it would be a second one, and the failure mode is a kit
    that rejects a record a newer core accepts.
    """

    records: tuple[Mapping[str, Any], ...]
    doc: Mapping[str, Any] | None
    parts: tuple[Mapping[str, Any], ...]
    pages: tuple[Mapping[str, Any], ...]
    blocks: tuple[Mapping[str, Any], ...]
    end: Mapping[str, Any] | None
    unknown: tuple[Mapping[str, Any], ...]

    @property
    def achieved(self) -> Mapping[str, Any]:
        """`doc.achieved`, or `{}` for a fragment with no `doc` record.

        `{}` rather than a raise: "there is no doc record" is a `contract` finding with its own
        assertion, and a `capability` suite that exploded on the way to making it would replace an
        actionable message with a traceback.
        """
        if self.doc is None:
            return {}
        value = self.doc.get("achieved")
        return value if isinstance(value, dict) else {}

    def part(self, path: str) -> Mapping[str, Any] | None:
        for record in self.parts:
            if record.get("path") == path:
                return record
        return None


def read_fragment(ref: ArtifactRef, blobs: MemoryBlobStore) -> Fragment:
    """Decode one `doc_fragment` ref into its records.

    A blob-backed ref is read through the store rather than through `ref.head()`: `head()` returns
    the first `INLINE_MAX` bytes and a truncated JSONL body would decode as a *shorter document*
    rather than as an error, which is the worst available failure for a suite that counts blocks.
    """
    if ref.inline is not None:
        body = ref.inline
    elif ref.blob is not None:
        with blobs.open(ref.blob) as fh:
            body = fh.read()
    else:  # pragma: no cover -- `ArtifactRef.__post_init__` forbids it.
        msg = "an ArtifactRef with neither inline nor blob"
        raise ValueError(msg)
    return decode_fragment(body)


def decode_fragment(body: bytes) -> Fragment:
    """The JSONL half of `read_fragment`, over bytes. One record per line, `t` naming the kind."""
    records: list[Mapping[str, Any]] = []
    for number, line in enumerate(body.splitlines(), start=1):
        if not line.strip():
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError as exc:
            msg = f"owdoc-fragment/1 line {number} is not JSON: {exc}"
            raise ValueError(msg) from None
        if not isinstance(record, dict):
            msg = f"owdoc-fragment/1 line {number} is a {type(record).__name__}, not an object"
            raise TypeError(msg)
        records.append(record)
    by_kind: dict[str, list[Mapping[str, Any]]] = {}
    for record in records:
        by_kind.setdefault(str(record.get("t", "")), []).append(record)
    known = {"doc", "part", "page", "block", "end"}
    unknown = tuple(r for kind, rows in by_kind.items() if kind not in known for r in rows)
    docs = by_kind.get("doc", [])
    ends = by_kind.get("end", [])
    return Fragment(
        records=tuple(records),
        doc=docs[0] if docs else None,
        parts=tuple(by_kind.get("part", ())),
        pages=tuple(by_kind.get("page", ())),
        blocks=tuple(by_kind.get("block", ())),
        end=ends[-1] if ends else None,
        unknown=unknown,
    )


@dataclass(frozen=True, slots=True)
class ParseRun:
    """One `parse()` call and everything it produced. What `run_parse()` returns."""

    fixture: Fixture
    result: DriverResult
    fragment: Fragment
    call: Call
    body: bytes

    @property
    def blocks(self) -> tuple[Mapping[str, Any], ...]:
        return self.fragment.blocks


def run_parse(
    driver: object,
    fixture: Fixture,
    tmpdir: Path,
    *,
    deadline_ms: int = DEFAULT_DEADLINE_MS,
    max_output_bytes: int = DEFAULT_MAX_OUTPUT_BYTES,
    cancel_after_progress: int = 0,
    part: str = "",
    declared_byte_len: int = 0,
) -> ParseRun:
    """Seed the fixture into a fresh store, call `parse()`, and decode what came back.

    A FRESH `MemoryBlobStore` and a fresh `KitIO` per call, always. Sharing either across two runs
    would make `idempotence`'s "the same input twice through one process" a test of the harness's
    caching rather than of the driver's statelessness, which is the defect that suite exists to
    catch (`hidden per-instance state`, 04-driver-system.md:2076).
    """
    from omniweave_ports.types import PartSelector, UnitRef  # noqa: PLC0415

    blobs = MemoryBlobStore(tmpdir / "blobs")
    digest = blobs.add(fixture.data)
    io_obj = make_io(
        blobs,
        tmpdir / "tmp",
        deadline_ms=deadline_ms,
        max_output_bytes=max_output_bytes,
        cancel_after_progress=cancel_after_progress,
    )
    unit = UnitRef(
        uri=fixture.path.as_uri(),
        part=part,
        content_sha256=digest,
        # `declared_byte_len` lets a suite state a length that disagrees with the blob, which is
        # the only way to ask "does this driver re-check a HOST-enforced ceiling?" without a host.
        # The bytes behind `content_sha256` are unchanged, so a driver that reads the stream gets a
        # real document and a driver that trusts `byte_len` gets the oversized number DR20 says it
        # must not act on. `limits._input_ceiling_assertions` is the one caller.
        byte_len=declared_byte_len or fixture.byte_len,
        # The routed media type, which the host knows before INVOKE and a driver is entitled to
        # read. `None` when the fixture carries no sidecar, which is also what a host that could
        # not decide would pass -- so a driver is exercised on both paths across a corpus.
        media_type=fixture.media_type,
    )
    result = driver.parse(unit, PartSelector(), io_obj)  # type: ignore[attr-defined]
    produced = result.produced
    fragments = [ref for ref in produced if ref.kind == "doc_fragment"]
    if not fragments:
        empty = Fragment((), None, (), (), (), None, ())
        return ParseRun(fixture, result, empty, io_obj.call(), b"")
    ref = fragments[0]
    body = ref.inline if ref.inline is not None else _blob_bytes(ref, blobs)
    return ParseRun(fixture, result, decode_fragment(body), io_obj.call(), body)


def _blob_bytes(ref: ArtifactRef, blobs: MemoryBlobStore) -> bytes:
    with blobs.open(str(ref.blob)) as fh:
        return fh.read()


def nfc(text: str) -> str:
    """`unicodedata.normalize("NFC", s)` and nothing else.

    03-document-model.md section 7.2 is this predicate's sole home and 13-quality.md:1041-1043 is
    emphatic about which normaliser INV-10 proves under: "`nfc()` -- `unicodedata.normalize("NFC",
    s)` and nothing else". Not `normalize_k`, which casefolds and would let a block reading `abc`
    prove `verbatim` against source bytes reading `ABC`; and not `normalize_eval`, which is the
    evaluator's comparison normaliser and folds quotes.

    `omniweave_core.ident.nfc` is the same function and the kit calls it; this wrapper exists so a
    suite reads `harness.nfc` beside `harness.read_fragment` rather than reaching across for one
    name. It delegates rather than re-implements.
    """
    from omniweave_core.ident import nfc as core_nfc  # noqa: PLC0415

    return core_nfc(text)


def part_bytes(fixture: Fixture) -> bytes:
    """The retained part's bytes. For this kit a fixture is one part, so it is the file.

    A driver that retains several parts is re-read per part by the `capability` suite through
    `Fragment.part()`; this helper is the one-part case, which is every `parse/1` driver whose
    `[limits] max_parts` is 1.
    """
    return fixture.data


def decode_span(data: bytes, start: int, length: int, codec: str) -> str | None:
    """INV-10's `bytes` branch, left side: `part_bytes[a : a+b].decode(*codec.split("/", 1))`.

    Returns `None` rather than raising for a span that is out of range or will not decode. A suite
    needs to say *which* fixture and *which* block failed and how; an exception out of here would
    put a `UnicodeDecodeError` where that message should be.
    """
    if start < 0 or length < 0 or start + length > len(data):
        return None
    name, _, errors = codec.partition("/")
    try:
        text = data[start : start + length].decode(name, errors or "strict")
    except (LookupError, UnicodeDecodeError, ValueError):
        return None
    return unicodedata.normalize("NFC", text)


@dataclass(frozen=True, slots=True)
class OriginCheck:
    """The verdict of one re-read: did this block's address still produce this block's text?

    `branch` is the `os_kind` that was taken and is carried because the three branches mean
    different things when they fail. `got` is what the re-read actually produced, truncated by the
    caller rather than here, because a suite wants it in an `Assertion` and a metric wants it in a
    failure list.
    """

    ok: bool
    branch: str
    detail: str
    got: str


def reverify_origin(
    data: bytes,
    origin: Mapping[str, Any],
    text: str,
    hook: object = None,
) -> OriginCheck:
    """INV-10's re-read, on the branch `os_kind` selects. **The one home of this decision.**

    Two callers need exactly this and they need it identically: the `capability` suite's P7, which
    asks it of every body block when the CARD declares `origin_span = "exact"`, and
    `evaluate.span_exact_rate`, which asks it of every block whose own `quote` claims `verbatim`.
    Those are different populations — a card's declaration and a block's claim are not the same
    statement — but the verification is one piece of arithmetic, and INV-21 has a name for the
    version of this where it lives in two files.

    Three branches, all named, because "a `bytes`-only property is inapplicable to the container
    formats it matters most for" (03:2990's P7 row). Only `bytes` is provable from
    `owdoc-fragment/1` alone: `nodepath` needs a node reader for the part's own format and `glyphs`
    needs the recorded `os_extractor` re-run, and both are the driver's dependencies rather than
    the kit's — so a driver claiming `exact` on either must ship a `verify_origin()` hook. Absent
    one, this reports what it could not do, with the branch named, and **never a pass**.
    """
    kind = str(origin.get("k", "none"))
    if kind == "bytes":
        got = decode_span(
            data,
            int(origin.get("start", -1)),
            int(origin.get("length", -1)),
            str(origin.get("codec", "utf-8")),
        )
        want = unicodedata.normalize("NFC", text)
        return OriginCheck(
            ok=got == want,
            branch=kind,
            detail="nfc(part_bytes[a : a+b].decode(codec)) == text (03 section 7.2)",
            got="<span out of range or undecodable>" if got is None else got,
        )
    if kind in {"nodepath", "glyphs"}:
        if hook is None:
            needs = "a node path resolver" if kind == "nodepath" else "the os_extractor"
            return OriginCheck(
                ok=False,
                branch=kind,
                detail=(
                    f"the {kind} branch needs the part's own reader ({needs}), which is the "
                    f"driver's dependency and not this kit's; a driver claiming exact on this "
                    f"branch must ship a {ORIGIN_VERIFIER}() hook"
                ),
                got="",
            )
        try:
            ok, why = hook(data, origin, text)  # type: ignore[operator]
        except Exception as exc:  # a hook that raises is a failed verification, not a kit crash.
            ok, why = False, f"{ORIGIN_VERIFIER}() raised {type(exc).__name__}: {exc}"
        return OriginCheck(
            ok=bool(ok),
            branch=kind,
            detail=why or f"the driver's own {ORIGIN_VERIFIER}() re-read the retained part",
            got=text if ok else str(why),
        )
    return OriginCheck(
        ok=False,
        branch=kind or "absent",
        detail=f"os_kind = {kind!r}; exact needs a re-verifiable OriginSpan (04:493)",
        got=kind or "absent",
    )


def iter_fixture_names(fixtures: Sequence[Fixture]) -> Iterator[str]:
    for fixture in fixtures:
        yield fixture.name
