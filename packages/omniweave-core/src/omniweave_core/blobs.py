"""The content-addressed asset store: the four-step CAS write protocol and its sweeps.

`asset.store_ref` and `part.store_ref` are `cas://ab/cd/<sha256>` references into
`.omniweave/cas/`, and there are **no inline bytes, ever** -- not in a table, not in a row
(07-store-and-retrieval.md section 3.11, :904-906; 03-document-model.md:2075, :2089). This module
is the only thing that writes, reads and deletes those bytes, and 02-architecture.md:241 names it
row 17 of the module register with exactly this surface: `put(BinaryIO) -> sha256`, `path(digest)`,
refcount, mark-and-sweep, a headroom file.

**Why this module sits at the top level of `omniweave_core` and not under `store/`**
(11-repo-layout.md:198 places it beside `locks.py`, `clock.py`, `cache.py`, `budget.py`,
`deps.py`, `events.py` and `work.py`). The bytes are on the filesystem and the *references* to them
are rows; INV-1 says a thing is a row or a blob and never both, and the seam between the two is
exactly this module's boundary. Being top-level makes it an **eager** module, so it may not import
`sqlite3` (INV-17) and may not import any of the nine LAZY names -- `model` included, which is why
every enum-shaped argument below is a plain `str` and why no `Degradation` is constructed here.

**The refcount is not in this module and cannot be.** A blob's reference count is a SQL aggregate
over `asset`, `part` and `cache_index` rows (07:930-935), and reading it needs the connection an
eager module is forbidden. So `sweep()` takes a `live` callable -- the same shape the plan gives the
other sweep across the same seam, `VectorBackend.sweep(live: Callable[[], Iterable[bytes]])` at
07:97. `live()` **is** the refcount, projected onto the only question the filesystem can answer.

**Two orderings are inverted from the obvious one, and both are load-bearing.**

1. **A write fsyncs the file before the rename and the directory after it** (07:906-909). Three
   steps would be enough for the bytes to land under the right name; the fourth is what stops the
   rename itself from being lost.
2. **A sweep deletes the file BEFORE the row** (07:930-932, restated at 08-runtime.md:1483-1486).
   The inverse leaves a dangling *file* -- an unreachable leak nothing will ever collect. This way
   the only reachable inconsistency is a dangling *row*, which is recoverable: a `miss_corrupt` on
   the next read, and `ow store fsck --cas` clears it. `sweep()` therefore takes the row-deleting
   callback as an argument and calls it itself, so a caller cannot choose the other order.

Digests here are **plain `hashlib.sha256` over the byte stream**, not one of
`omniweave_core.identity`'s helpers: those are domain-separated `ow128` recipes over model values
(`content_digest` at identity.py:303 hashes `kind`, `layer` and NFC text), whereas `part.sha256` is
declared `BLOB` over the container's own bytes at 03-document-model.md:2414 and the CAS path is that
digest's hex. The two are different facts and neither is the other's second home.

Stdlib only (INV-2, gate G1). Tier T-PUBLIC: 02-architecture.md section 2 row 17.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import time
from dataclasses import dataclass
from itertools import count
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING, BinaryIO, Final

from omniweave_core.config import KEYS
from omniweave_core.errors import ResourceLimit, StoreError, UsageError
from omniweave_core.limits import MAX_ASSET_BYTES, effective

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable, Iterator, Sequence

__all__ = [
    "CAS_SCHEME",
    "CITABLE_DECLARED_ORIGIN_SPANS",
    "FANOUT_DEPTH",
    "FANOUT_WIDTH",
    "HEADROOM_FILENAME",
    "NO_SPACE_DEGRADATION_KIND",
    "REVERIFIABLE_OS_KINDS",
    "SHA256_BYTES",
    "TMP_DIRNAME",
    "BlobStore",
    "Headroom",
    "SweepReport",
    "digests_of",
    "format_ref",
    "parse_ref",
    "ref_relative_path",
    "retains_part",
]


# --------------------------------------------------------------------------------------------
# 1. The reference grammar. `cas://ab/cd/<sha256>` and nothing else.
# --------------------------------------------------------------------------------------------

#: The one scheme, spelled as 07:904 and 03:2075 spell it, `//` included. A `store_ref` that does
#: not start with exactly this is not a CAS reference and is never repaired into one.
CAS_SCHEME: Final = "cas://"

#: 32 raw bytes, 64 hex characters. The width of `part.sha256` (03-document-model.md:2414).
SHA256_BYTES: Final = 32

#: Two levels of two hex characters: `ab/cd/`.
#:
#: **The arithmetic, because the number is the justification** (07:917-919). Two levels of two hex
#: characters is `256 * 256 = 65_536` leaf directories, uniformly loaded because a sha256 prefix is
#: uniform. At 10M blobs that is `10_000_000 / 65_536 ~= 152` entries per directory, which keeps
#: `readdir` cheap on every filesystem and keeps Windows Explorer usable. One level would hold
#: 39_062 entries per directory at the same corpus size; three would need 16.7M directories to hold
#: 10M files, so the directories would outnumber the blobs.
FANOUT_DEPTH: Final = 2
FANOUT_WIDTH: Final = 2

#: Inside `cas/`, always -- which is the whole point (07:911-914). See `BlobStore.tmp_root`.
TMP_DIRNAME: Final = "tmp"

#: The headroom file's name, at the top of `cas/`. It cannot collide with a fanout directory (two
#: hex characters) or with `tmp`, so neither sweep ever sees it.
HEADROOM_FILENAME: Final = "headroom.json"

_HEX_64 = re.compile(r"\A[0-9a-f]{64}\Z")
_HEX_2 = re.compile(r"\A[0-9a-f]{2}\Z")

#: One read of a stream being hashed into the CAS. 1 MiB, so a maximal asset is exactly 256 reads
#: (`MAX_ASSET_BYTES // 1 MiB == 256`) and the resident cost of `put()` is one chunk whatever the
#: input's size -- which is what makes the `MAX_ASSET_BYTES` refusal below a refusal rather than a
#: measurement taken after the memory was already spent (limits.py's `take(N+1)`-then-check rule).
_CHUNK_BYTES: Final = 1 << 20

_FIX_FSCK: Final = "ow store fsck --cas"

#: `os.O_BINARY` where it exists, `0` where it does not. THIS IS NOT A PORTABILITY ORNAMENT.
#:
#: `os.open` on Windows opens in the C runtime's *text* mode unless `O_BINARY` is in the flags, and
#: text mode rewrites every `0x0A` the process writes as `0x0D 0x0A` on its way to the disk. The
#: CAS write protocol at 07-store-and-retrieval.md:911-916 stages bytes through `cas/tmp/<name>`
#: and then renames the staged file under its own sha256, and step 3's whole safety argument is
#: "an overwrite is a no-op **because the name IS the digest**" (07:914). A translating write
#: falsifies that sentence for every blob containing a newline: the file under `ab/cd/<sha256>`
#: hashes to something else, and every reader that trusts the name instead of re-hashing -- which
#: is every reader, by design -- serves bytes that are not the bytes that were stored.
#:
#: It is invisible on POSIX, invisible for any blob with no `0x0A` in it, and invisible to a test
#: that round-trips through `BlobStore` alone, because `put` hashes the stream it was HANDED and
#: never re-reads what landed. What sees it is INV-10's bytes branch (0001_init.sql:409-411)
#: re-deriving a block's text from `part` bytes read back out of the CAS -- which is exactly
#: 16-roadmap.md:435's P2 demo clause, and exactly how it was found.
#:
#: `getattr` rather than `os.O_BINARY`: the name does not exist on POSIX and `0` is the identity
#: for `|`, so one spelling is correct on both.
_O_BINARY: Final[int] = getattr(os, "O_BINARY", 0)


def _as_digest(digest: bytes | str) -> bytes:
    """The 32 raw bytes, from either spelling, refusing anything else.

    Accepting both is not laxity: a `part.sha256` read back out of the store is `bytes`, and a
    digest read out of a `cas://` reference or a log line is hex `str`. A helper that took only one
    would push a `bytes.fromhex` into every caller, and that is where a caller writes
    `bytes.fromhex(ref)` over the whole reference and gets a `ValueError` instead of a refusal.
    """
    if isinstance(digest, str):
        if not _HEX_64.match(digest):
            raise UsageError(
                f"a CAS digest is 64 lowercase hex characters, not {digest!r}", fix=_FIX_FSCK
            )
        return bytes.fromhex(digest)
    if isinstance(digest, (bytes, bytearray, memoryview)):
        raw = bytes(digest)
        if len(raw) != SHA256_BYTES:
            raise UsageError(f"a CAS digest is {SHA256_BYTES} bytes, not {len(raw)}", fix=_FIX_FSCK)
        return raw
    raise UsageError(
        f"a CAS digest is bytes or 64-char hex, not {type(digest).__name__}", fix=_FIX_FSCK
    )


def ref_relative_path(digest: bytes | str) -> PurePosixPath:
    """`ab/cd/<sha256>` -- the fanout path, relative to `cas/`.

    `PurePosixPath` and not `Path`: this is the *reference's* spelling, which is `/`-separated on
    every platform because it is stored in a row and read back on another machine. The on-disk path
    is `BlobStore.path()`, and that is the only place the separator becomes the host's.
    """
    hexed = _as_digest(digest).hex()
    parts = [hexed[i * FANOUT_WIDTH : (i + 1) * FANOUT_WIDTH] for i in range(FANOUT_DEPTH)]
    return PurePosixPath(*parts, hexed)


def format_ref(digest: bytes | str) -> str:
    """The `cas://ab/cd/<sha256>` reference for a digest.

    Formatting is derivation, never lookup: the reference carries no information the digest does
    not, which is exactly why step 3 of the write protocol may overwrite (07:908 -- "overwrite is a
    no-op because the name IS the digest").
    """
    return f"{CAS_SCHEME}{ref_relative_path(digest)}"


def parse_ref(ref: str) -> bytes:
    """The 32 raw digest bytes of a `cas://ab/cd/<sha256>` reference, or a refusal.

    **This is the path-confinement boundary for a stored reference, and it confines by grammar
    rather than by resolution.** `omniweave_core.paths.confine()` (14-security.md:275, :1834) is the
    framework's one path-confinement function, and it answers a different question -- "does this
    attacker-chosen *name* stay under a base" -- by resolving and then `relative_to`-ing. A CAS
    reference has no attacker-chosen name at all: every segment is fixed by the digest, so
    `cas://../../etc/passwd`, its percent-encoded spelling `cas://%2e%2e/%2e%2e/etc/passwd`, an
    absolute member, a Windows drive-relative member, a reserved device name and an alternate data
    stream are all refused by the same three checks, before any path exists to resolve.
    14-security.md:300 calls `confine()` "a check, and a check followed by an open is a TOCTOU
    race"; a grammar has no such window, because there is nothing to re-derive between the check and
    the open.

    Both fanout segments are checked against the digest rather than merely for hex-ness, so a
    reference whose directories disagree with its own name -- the shape a hand-edited row takes --
    is refused instead of quietly reading the file the digest names.
    """
    if not isinstance(ref, str):
        raise UsageError(f"a CAS reference is a str, not {type(ref).__name__}", fix=_FIX_FSCK)
    if not ref.startswith(CAS_SCHEME):
        raise UsageError(f"a CAS reference starts with {CAS_SCHEME!r}: {ref!r}", fix=_FIX_FSCK)
    segments = ref[len(CAS_SCHEME) :].split("/")
    if len(segments) != FANOUT_DEPTH + 1:
        raise UsageError(
            f"a CAS reference has exactly {FANOUT_DEPTH + 1} segments: {ref!r}", fix=_FIX_FSCK
        )
    *fanout, name = segments
    if not _HEX_64.match(name):
        raise UsageError(
            f"a CAS reference names a 64-char lowercase sha256: {ref!r}", fix=_FIX_FSCK
        )
    for index, segment in enumerate(fanout):
        want = name[index * FANOUT_WIDTH : (index + 1) * FANOUT_WIDTH]
        if not _HEX_2.match(segment) or segment != want:
            raise UsageError(
                f"segment {index} of {ref!r} is {segment!r}, but its digest says {want!r}",
                fix=_FIX_FSCK,
            )
    return bytes.fromhex(name)


def digests_of(refs: Sequence[str]) -> tuple[bytes, ...]:
    """Parse many stored references, refusing the whole batch on the first bad one.

    Batch-or-nothing because the caller is `sweep`'s `live` or a hydration path, and a partial parse
    there would silently *narrow* a mark set -- which is how a live blob gets deleted.
    """
    return tuple(parse_ref(ref) for ref in refs)


# --------------------------------------------------------------------------------------------
# 2. `part` retention at `[store] retain_parts`. 07 section 8.1 (:2539-2543).
# --------------------------------------------------------------------------------------------

#: The `Capabilities.origin_span` declarations `when_citable` retains for (07:2540-2541,
#: 18-api-sketch.md:1632, 03-document-model.md:3023). `"none"` is the third member of that `Literal`
#: (model/block.py:304) and is absent here on purpose.
CITABLE_DECLARED_ORIGIN_SPANS: Final[frozenset[str]] = frozenset({"exact", "normalized"})

#: INV-10's three re-verifiable branches, by `origin_span_kind` (01-principles.md:310-312).
#: `pixels` and `none` are absent because "there is nothing to re-read"
#: (03-document-model.md:1652).
#:
#: A subset predicate over `model.enums.OsKind`, spelled in `str` because `model` is LAZY and this
#: module is eager (G17). It is not a second home for the domain -- the five members live at
#: model/enums.py:283-288 and in `enum_val` -- but the *branch list* has no code home yet;
#: `MAX_QUOTE_BY_OS_KIND` (03 section 8.3) is where it should be derived from once that lands.
REVERIFIABLE_OS_KINDS: Final[frozenset[str]] = frozenset({"bytes", "nodepath", "glyphs"})

#: The `Degradation.kind` the runtime latches on the first no-space refusal (08-runtime.md:1494,
#: 15-observability.md:1092). Named here as a **string** and never constructed: `Degradation` is
#: L2's and L2 is LAZY. `BlobStore` raises and latches; the runtime maps that to the `Degradation`.
NO_SPACE_DEGRADATION_KIND: Final = "cache_disabled_no_space"

_RETAIN_PARTS_KEY: Final = "store.retain_parts"
_MIN_FREE_BYTES_KEY: Final = "cache.min_free_bytes"


def retains_part(policy: str, *, declared_origin_span: str, os_kind: str | None = None) -> bool:
    """Does this `part`'s `blob` reach CAS -- i.e. is `part.store_ref` non-NULL?

    `add_part`'s nullable `blob` **is** the retention policy in the signature
    (03-document-model.md:601-605), and `store_ref TEXT` is "NULL => bytes were not retained"
    (03-document-model.md:2415). This predicate is the decision that fills that column or leaves it.

    **Retention is load-bearing in five places** -- the reason 16-roadmap.md:419 prices W2.6's tests
    above its code, and the reason a three-line predicate carries this docstring:

    1. **INV-10** (01-principles.md:309-313, 03-document-model.md:1650-1653) makes
       `part.store_ref IS NOT NULL` a *precondition* of `quote = 'verbatim'`. An unretained part
       cannot be re-read, so the claim cannot be proved, so it is not made.
    2. **X8's three re-read branches** -- `bytes`, `nodepath`, `glyphs` (charter section 5 X8, cited
       at 03-document-model.md:1471; 00-vision.md:214) -- all re-read the retained part. That is
       what `REVERIFIABLE_OS_KINDS` above is.
    3. **Q-G6** gates `span_exact_rate` at **1.000** on a deterministic sample of n = 1000 blocks,
       as a hard gate and not a metric (01-principles.md:327-329, 03-document-model.md:1652-1653).
       A block claiming `verbatim` with no retained part fails it.
    4. **SV13** -- `byte_exact()` has one definition and one call site (18-api-sketch.md:652) -- and
       it proves the claim by re-reading `store_ref`.
    5. **The storage projection**: retention "roughly doubles corpus storage" (07:1042, 12:922),
       ~71 GB of CAS on the 100k reference ingest (12-performance.md:355). That number is F32, the
       measurement that may yet make `never` the default (07:2541-2543, 17-risks.md:527).

    **The plan contradicts itself about which axis `when_citable` reads, and the reading below has
    the definition sites.** 07:2540-2541 ("retain a `part` iff the producing driver declared
    `origin_span` in `{exact, normalized}` for it"), 18-api-sketch.md:1632,
    03-document-model.md:3023 and `adr/0005-byte-exactness-chain.md`:100 all define it over the
    **declared card**, and
    adr/0005:107 says why it must be the card and not `achieved`: "retention happens during the
    parse and `achieved` is computed at `end_doc`". 02-architecture.md:486 instead writes the worked
    case as "retained because `origin_span='glyphs'`" -- but `glyphs` is an `origin_span_kind` value
    (model/enums.py:285) and not a `Capabilities.origin_span` value (model/block.py:304) at all. Two
    different closed domains, one sentence.

    Both readings are honoured, and `os_kind` is optional so neither is lost:

    * with `os_kind=None` this is 07:2540's `iff` over the card, exactly;
    * with `os_kind` given the card's decision is **narrowed** by INV-10's branch list, which is
      02:486's cell read as a claim about the part. The narrowing can never lose a `verbatim`, which
      is the only direction that matters: 03-document-model.md:1652 says `pixels` and `none` "can
      never reach it: there is nothing to re-read", so bytes retained for such a part have no
      possible consumer and are pure cost against item 5 above.

    `policy` is validated against `config.KEYS["store.retain_parts"].choices` rather than against a
    literal tuple here, so the three policy names keep one home (INV-21).
    """
    choices = KEYS[_RETAIN_PARTS_KEY].choices
    if policy not in choices:
        raise UsageError(
            f"[store] retain_parts is one of {choices}, not {policy!r}", fix="ow doctor --config"
        )
    if policy == "never":
        return False
    if policy == "always":
        return True
    if declared_origin_span not in CITABLE_DECLARED_ORIGIN_SPANS:
        return False
    return os_kind is None or os_kind in REVERIFIABLE_OS_KINDS


# --------------------------------------------------------------------------------------------
# 3. The headroom file and the write refusal. 08-runtime.md section 4.7(a) (:1489-1497).
# --------------------------------------------------------------------------------------------

_HEADROOM_SCHEMA: Final = 1


@dataclass(frozen=True, slots=True)
class Headroom:
    """One measurement of free space against `cache.min_free_bytes`, plus the latch.

    **Why a file and not an attribute.** 08-runtime.md:1489 says `blobs.py` "maintains a headroom
    file" and is silent on its shape, so the shape is decided here by what the file has to do:
    08:1493-1496 makes the *first* refusal latch for the rest of the run, with every subsequent
    write "skipped without an event storm". A latch held in an attribute is per-process, and the
    runtime is multi-process by construction (`work` rows, leases, a claim batch per cost class), so
    one worker would keep hammering a full disk after another had already given up. The file is the
    latch's only shared home, and it is also what lets `ow cost` and `ow doctor` report the refusal
    without re-measuring.

    `measured_ns` is a `time.monotonic_ns()` reading, not a wall clock: `time.time` and
    `time.perf_counter` are semgrep-banned in library code (02-architecture.md:392) and the only
    question ever asked of this field is "how long ago", which is what a monotonic clock answers.
    """

    free_bytes: int
    min_free_bytes: int
    measured_ns: int
    latched: bool

    @property
    def refuses(self) -> bool:
        """True iff a write must be refused -- either measured short, or already latched."""
        return self.latched or self.free_bytes < self.min_free_bytes


@dataclass(frozen=True, slots=True)
class SweepReport:
    """What one mark-and-sweep pass did. Counted, because `ow store fsck --cas` prints it."""

    scanned: int
    files_deleted: int
    rows_forgotten: int
    bytes_reclaimed: int


# --------------------------------------------------------------------------------------------
# 4. `BlobStore`. 02-architecture.md:241 fixes the name and the surface.
# --------------------------------------------------------------------------------------------

#: Bumped per staged file, so two writers inside one process cannot pick the same temp name.
_TMP_SEQUENCE = count()


class BlobStore:
    """The CAS under one `cas/` root: `put`, `path`, `open`, the two sweeps, the headroom file.

    Construction takes an **existing** root, for `confine()`'s own stated reason
    (14-security.md:278-280): a resolver that accepts a missing base is usable as a pre-build file
    oracle. The root is resolved once, here, and no later call re-derives it from a caller's string
    -- which is the rule 14-security.md:305-309 makes a semgrep target.
    """

    __slots__ = ("_latched", "_max_bytes", "_min_free_bytes", "_monotonic_ns", "_root")

    def __init__(
        self,
        root: str | os.PathLike[str],
        *,
        min_free_bytes: int | None = None,
        max_bytes: int | None = None,
        monotonic_ns: Callable[[], int] = time.monotonic_ns,
    ) -> None:
        resolved = Path(root).resolve()
        if not resolved.is_dir():
            raise StoreError(
                f"the CAS root {resolved} does not exist; a root is created, never resolved into",
                fix="ow store init",
            )
        self._root = resolved
        declared_min_free = KEYS[_MIN_FREE_BYTES_KEY].default
        if not isinstance(declared_min_free, int):  # pragma: no cover - a declaration-site guard
            raise StoreError(
                f"[{_MIN_FREE_BYTES_KEY}] declares a non-int default {declared_min_free!r}",
                fix="ow doctor --config",
            )
        self._min_free_bytes = declared_min_free if min_free_bytes is None else min_free_bytes
        # `effective()` and not `min()`: limits.py:129 is the one home for what a tenant may do to
        # a ceiling, and a tenant may only clamp DOWN (INV-22).
        self._max_bytes = effective(max_bytes, None, MAX_ASSET_BYTES)
        self._monotonic_ns = monotonic_ns
        self._latched = False

    # -- layout ------------------------------------------------------------------------------

    @property
    def root(self) -> Path:
        """`cas/`. Resolved once, at construction."""
        return self._root

    @property
    def tmp_root(self) -> Path:
        """`cas/tmp/`.

        **Inside `cas/`, always** (07:911-914). Step 3 is `os.replace`, which is atomic *within one
        filesystem* and raises `OSError(EXDEV)` across one; a "download to the system temp dir then
        move" implementation therefore fails on exactly the machines that separate `/tmp` -- the
        ones with the least disk. Making the staging directory a child of the destination's own root
        makes the cross-device case unrepresentable rather than merely unlikely.
        """
        return self._root / TMP_DIRNAME

    @property
    def headroom_path(self) -> Path:
        """`cas/headroom.json`."""
        return self._root / HEADROOM_FILENAME

    @property
    def max_bytes(self) -> int:
        """The effective per-blob ceiling: `min(tenant clamp, MAX_ASSET_BYTES)`."""
        return self._max_bytes

    def path(self, digest: bytes | str) -> Path:
        """The on-disk path of a blob: `cas/ab/cd/<sha256>`. Derived, never looked up."""
        return self._root.joinpath(*ref_relative_path(digest).parts)

    def ref(self, digest: bytes | str) -> str:
        """`cas://ab/cd/<sha256>` for a digest this store holds or will hold."""
        return format_ref(digest)

    def has(self, digest: bytes | str) -> bool:
        """Is this blob present? `False` against a non-NULL `store_ref` is the dangling row."""
        return self.path(digest).is_file()

    # -- the read path -----------------------------------------------------------------------

    def open(self, digest: bytes | str) -> BinaryIO:
        """Open a blob for reading, refusing anything that resolves outside `cas/`.

        Two independent refusals, because they answer different attacks:

        1. **the grammar** -- `_as_digest` accepts 32 bytes or 64 lowercase hex and nothing else, so
           no traversal, no percent-encoding, no absolute member and no device name can reach a path
           at all. This is the check `parse_ref` documents.
        2. **the resolution** -- the derived path is `resolve()`d and required to stay under the
           root resolved at construction. The grammar makes the *name* safe; what this catches is
           a **planted symlink or NTFS junction** at `cas/ab/cd/<digest>` pointing at `/etc/shadow`,
           which is a legal name for an illegal target. 14-security.md:298-309 is explicit that
           resolution comes before the containment test and that the caller must use the resolved
           value -- so the resolved value is what is opened.

        `OW_PATH_OUTSIDE_ROOTS` is the code 14-security.md:293 assigns the refusal, carried in
        `codes.toml` as `OW-A-007` under `SurfaceError`.
        """
        target = self.path(digest)
        real = target.resolve()
        if not real.is_relative_to(self._root):
            raise UsageError(
                f"{target} resolves to {real}, outside the CAS root {self._root}",
                symbol="OW_PATH_OUTSIDE_ROOTS",
                fix=_FIX_FSCK,
            )
        try:
            return real.open("rb")
        except FileNotFoundError as exc:
            raise StoreError(
                f"no CAS blob at {format_ref(digest)}: the row is dangling", fix=_FIX_FSCK
            ) from exc

    def open_ref(self, ref: str) -> BinaryIO:
        """`open()` a stored `cas://` reference, parsing it first."""
        return self.open(parse_ref(ref))

    # -- the write path: the four steps, in order --------------------------------------------

    def put(self, fh: BinaryIO) -> bytes:
        """Write a stream into the CAS and return its raw sha256. The four steps of 07:904-909.

        ```text
        1. write bytes to  cas/tmp/<unique>        same filesystem as cas/, ALWAYS
        2. fsync the file, then close              else a rename can outlive the data
        3. os.replace(tmp, cas/ab/cd/<sha256>)     atomic within one filesystem; overwrite is a
                                                   no-op because the name IS the digest
        4. fsync the containing directory          else the rename can be lost on a crash (POSIX)
        ```

        Each step's own failure is named at its site below. The digest is computed *while*
        streaming, so the bytes are never resident: `put` holds one `_CHUNK_BYTES` buffer whatever
        the input's size, which is what makes the `MAX_ASSET_BYTES` refusal a refusal.

        **07:906 spells the temp name `<uuid4>` and this writes a different one.** `uuid.uuid4` is
        semgrep-banned across `packages/*/src/**` with no exemption (02-architecture.md:392,
        tools/gate_semgrep.py:323-329), beside `random`, `secrets` and `time.time`, because an
        ambient nondeterministic input in library code is what the determinism gates exist to
        prevent. The name here is `<pid>-<counter>` and its uniqueness is **proved rather than
        assumed**: step 1 opens with `O_CREAT | O_EXCL`, so a collision -- including the one uuid4
        cannot avoid either, a recycled pid landing on a temp file abandoned by a dead process -- is
        an `EEXIST` that retries on the next counter value instead of corrupting a stranger's write.
        The honest residue is a shared filesystem where `O_EXCL` is not atomic (older NFS) and two
        machines pick the same pid; 07:911 already requires `cas/tmp/` to be on `cas/`'s own
        filesystem, so that is a store deployed against its own precondition.

        Raises `ResourceLimit` naming the knob for all three refusals: no headroom
        (`cache.min_free_bytes`, 08:1490), ENOSPC mid-write (07:928-930) and over-size
        (`MAX_ASSET_BYTES`, 07:934).
        """
        self._refuse_without_headroom()
        self.tmp_root.mkdir(parents=True, exist_ok=True)

        # ---- step 1: write the bytes to cas/tmp/, on cas/'s own filesystem. ----------------
        # The failure this prevents (07:911-914): a temp file in the system temp dir makes step 3
        # raise OSError(EXDEV) on every machine with a separate /tmp.
        tmp_path, fd = self._create_tmp()
        try:
            try:
                digest = self._stream(fh, fd, tmp_path)
                # ---- step 2: fsync the file, THEN close. ------------------------------------
                # The failure this prevents (07:907, "else a rename can outlive the data"): the
                # rename in step 3 can reach the disk before the data does, leaving a file under a
                # digest name whose contents are not that digest. Content-addressing may never
                # allow that, because every reader trusts the name instead of re-hashing.
                os.fsync(fd)
            finally:
                os.close(fd)

            # ---- step 3: os.replace into cas/ab/cd/<sha256>. -------------------------------
            # `Path.replace` IS `os.replace` (ruff PTH105 asks for this spelling), so 07:908's
            # step is literally what runs. Atomic within one filesystem, and an overwrite is a
            # harmless no-op **because the name IS the digest**: whatever is already there hashes
            # to the same value, so a concurrent writer of identical content cannot invalidate a
            # reader's open file.
            final = self.path(digest)
            final.parent.mkdir(parents=True, exist_ok=True)
            tmp_path.replace(final)
        except BaseException:
            # Steps 1 to 3 are one recovery scope, because the staged file is unreferenced for the
            # whole of it and referenced the instant step 3 returns. 07:930 assigns the abandoned
            # file to the startup sweep, because a process that is SIGKILLed cannot unlink
            # anything; this unlink is belt to that braces and is never the mechanism --
            # `sweep_tmp()` is still what makes the guarantee.
            tmp_path.unlink(missing_ok=True)
            raise

        # ---- step 4: fsync the containing directory. ---------------------------------------
        self._fsync_dir(final.parent)
        return digest

    def _create_tmp(self) -> tuple[Path, int]:
        """Step 1's `O_CREAT | O_EXCL` open, retried past a collision. Returns `(path, fd)`.

        `_O_BINARY` is in the flags for the reason its own comment gives at length: without it a
        Windows `os.open` translates `0x0A` to `0x0D 0x0A` and the file that lands under a digest
        name is not the file that hashes to it.
        """
        pid = os.getpid()
        while True:
            candidate = self.tmp_root / f"{pid}-{next(_TMP_SEQUENCE)}"
            try:
                # 0o600: a staged asset is never group- or world-readable, not even for the
                # milliseconds before step 3 renames it under the corpus's own permissions.
                fd = os.open(candidate, os.O_WRONLY | os.O_CREAT | os.O_EXCL | _O_BINARY, 0o600)
            except FileExistsError:
                continue  # the retry IS the uniqueness proof; see `put`'s docstring
            except OSError as exc:
                raise self._no_space(exc, candidate) from exc
            return candidate, fd

    def _stream(self, fh: BinaryIO, fd: int, tmp_path: Path) -> bytes:
        """Hash and write in one pass, refusing over-size *before* the byte is written.

        `take(N+1)`-then-check, as limits.py's module docstring requires: at most `max_bytes + 1`
        bytes are ever read, at most `_CHUNK_BYTES` are ever resident, and the over-size chunk is
        refused before `os.write`. A 4 GiB stream therefore costs one chunk of memory and at most
        `max_bytes` of transient disk rather than 4 GiB of either.
        """
        import hashlib  # noqa: PLC0415 -- use-time, so nothing here runs at import (G17's rule)

        hasher = hashlib.sha256()
        total = 0
        limit = self._max_bytes
        while True:
            want = min(_CHUNK_BYTES, limit + 1 - total)
            if want <= 0:  # pragma: no cover - the refusal below fires first, always
                break
            chunk = fh.read(want)
            if not chunk:
                break
            total += len(chunk)
            if total > limit:
                raise ResourceLimit(
                    f"asset exceeds MAX_ASSET_BYTES ({limit} bytes) at byte {total}",
                    limit="MAX_ASSET_BYTES",
                    fix="split the asset, or clamp [limits] below the ceiling; widening is a fork",
                )
            hasher.update(chunk)
            try:
                written = 0
                while written < len(chunk):
                    written += os.write(fd, chunk[written:])
            except OSError as exc:
                raise self._no_space(exc, tmp_path) from exc
        return hasher.digest()

    def _fsync_dir(self, directory: Path) -> bool:
        """Step 4. Returns whether the durability was actually bought.

        The failure it prevents (07:909): on POSIX a rename is a directory-entry mutation, and
        `fsync` on the *file* says nothing about the directory that names it, so a crash after step
        3 can lose the rename while the bytes sit in `cas/tmp/` under a name nothing references.

        **Windows cannot do this, and the cost is bounded.** `os.open` on a directory raises there
        -- there is no directory handle to `fsync` -- and 07:909's own parenthesis says "(POSIX)",
        so the plan's cited reason is platform-specific rather than universal. What Windows loses is
        *only step 4*: step 2 still fsyncs the file, so a partial blob can never appear under a
        digest name, and the worst a crash in the step-3/step-4 window can produce is a lost rename
        -- a `part` row whose `store_ref` names a missing file. That is precisely the **dangling
        row** the sweep ordering already elects as the one reachable inconsistency (07:930-932):
        recoverable, detected by `has()` or by `ow store fsck --cas`, and repaired by re-`put`ting
        bytes that are by definition still derivable, because a CAS blob is content and content is
        re-fetchable. A dangling *file* -- the leak -- stays impossible either way.
        """
        flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
        try:
            fd = os.open(directory, flags)
        except OSError:  # pragma: no cover - the Windows branch; see the docstring
            return False
        try:
            os.fsync(fd)
        except OSError:  # pragma: no cover - some filesystems refuse a directory fsync
            return False
        finally:
            os.close(fd)
        return True

    # -- the headroom file -------------------------------------------------------------------

    def headroom(self, *, measure: bool = True) -> Headroom:
        """The current headroom, measured unless the latch is already set.

        Once latched there is no measurement at all, which is 08:1495's "every subsequent write is
        skipped without an event storm": one `ow cost` line at the end of the run rather than one
        `statvfs` and one event per skipped blob.
        """
        stored = self._read_headroom()
        if stored is not None and stored.latched:
            self._latched = True
            return stored
        if self._latched:
            return Headroom(0, self._min_free_bytes, self._monotonic_ns(), latched=True)
        if not measure:
            return stored or Headroom(-1, self._min_free_bytes, self._monotonic_ns(), latched=False)
        free = shutil.disk_usage(self._root).free
        return Headroom(free, self._min_free_bytes, self._monotonic_ns(), latched=False)

    def _refuse_without_headroom(self) -> None:
        """08-runtime.md section 4.7(a): refuse, latch, and name the knob.

        The refusal is `ResourceLimit(limit="cache.min_free_bytes")`, and **the caller must not turn
        it into a unit failure**. 08:1490-1493 is explicit: "failing the *work* because the *cache*
        is full loses correctness for no reason, and `RESOURCE_LIMIT` would then halve every batch
        (section 1.6) and retry five times against a disk that is still full". `with_cache` catches
        this, latches `Degradation(kind=NO_SPACE_DEGRADATION_KIND)` naming `cache.min_free_bytes`,
        and becomes a pass-through for the rest of the run; work continues, uncached, and `ow cost`
        shows what that cost.
        """
        state = self.headroom()
        if not state.refuses:
            return
        self._latch_no_space(state)
        raise ResourceLimit(
            f"free space under {self._root} is {state.free_bytes} bytes, below "
            f"[cache] min_free_bytes = {state.min_free_bytes}; cache writes are disabled for the "
            f"rest of the run ({NO_SPACE_DEGRADATION_KIND})",
            limit=_MIN_FREE_BYTES_KEY,
            fix="ow store gc --cas   # or raise [cache] min_free_bytes",
        )

    def _latch_no_space(self, state: Headroom) -> None:
        """Write the latch through, best-effort.

        Best-effort on purpose: the condition being recorded is "the disk is full", so the write
        that records it is the write most likely to fail. The in-process `_latched` flag is the
        fallback, and its cost when the file write fails is that a *second* process re-measures once
        -- one `statvfs`, not an event storm.
        """
        self._latched = True
        self._write_headroom(
            Headroom(state.free_bytes, state.min_free_bytes, self._monotonic_ns(), latched=True)
        )

    def clear_latch(self) -> None:
        """Forget the no-space latch. A new run's business, never a retry's inside one run."""
        self._latched = False
        self.headroom_path.unlink(missing_ok=True)

    def _read_headroom(self) -> Headroom | None:
        """The stored measurement, or `None` if there is none this process can trust.

        A missing, unreadable or malformed file degrades to `None` rather than raising: the file is
        a cache of a `statvfs`, so the worst a corrupt one may cost is one syscall. Raising here
        would let a truncated JSON file fail every write in the run.
        """
        try:
            raw = json.loads(self.headroom_path.read_text("utf-8"))
        except (OSError, ValueError):
            return None
        if not isinstance(raw, dict) or raw.get("schema") != _HEADROOM_SCHEMA:
            return None
        try:
            return Headroom(
                free_bytes=int(raw["free_bytes"]),
                min_free_bytes=int(raw["min_free_bytes"]),
                measured_ns=int(raw["measured_ns"]),
                latched=bool(raw["latched"]),
            )
        except (KeyError, TypeError, ValueError):
            return None

    def _write_headroom(self, state: Headroom) -> None:
        """Replace the headroom file atomically, or give up quietly.

        Atomically because two processes latching at once must not leave half a JSON object behind,
        and the staging file goes in `cas/tmp/` for the same reason `put`'s does: `os.replace` is
        atomic within one filesystem and nowhere else.
        """
        payload = json.dumps(
            {
                "schema": _HEADROOM_SCHEMA,
                "free_bytes": state.free_bytes,
                "min_free_bytes": state.min_free_bytes,
                "measured_ns": state.measured_ns,
                "latched": state.latched,
                "knob": _MIN_FREE_BYTES_KEY,
                "degradation": NO_SPACE_DEGRADATION_KIND,
            },
            sort_keys=True,
        )
        try:
            self.tmp_root.mkdir(parents=True, exist_ok=True)
            staged = self.tmp_root / f"headroom-{os.getpid()}-{next(_TMP_SEQUENCE)}"
            staged.write_text(payload, "utf-8")
            staged.replace(self.headroom_path)
        except OSError:  # pragma: no cover - the full-disk branch this exists to survive
            return

    # -- the two sweeps ----------------------------------------------------------------------

    def sweep_tmp(self) -> int:
        """The startup sweep of `cas/tmp/`. Returns how many staged files it unlinked.

        This is the only cleanup for two failures the write path cannot clean up after itself
        (07:928-930): **ENOSPC in step 1**, where the process may not have the disk to do anything
        else, and **a SIGKILL between steps 1 and 3**, where the process no longer exists. Run it at
        store open, before any `put`.

        A staged file is never referenced by a row -- it has no digest name yet -- so unlinking one
        unconditionally cannot orphan anything, and nothing already committed can be reached from
        here. That asymmetry is why this sweep needs no `live` callable while `sweep()` does.
        """
        removed = 0
        for entry in self._iter_tmp():
            try:
                entry.unlink()
            except OSError:  # pragma: no cover - a racing writer still holds its own file
                continue
            removed += 1
        return removed

    def _iter_tmp(self) -> Iterator[Path]:
        if not self.tmp_root.is_dir():
            return
        with os.scandir(self.tmp_root) as entries:
            for entry in entries:
                if entry.is_file():
                    yield Path(entry.path)

    def sweep(
        self,
        live: Callable[[], Iterable[bytes]],
        *,
        forget: Callable[[bytes], None] | None = None,
    ) -> SweepReport:
        """Mark and sweep: delete every blob `live()` does not name, **file before row**.

        `live` is the mark phase and it is a **callable**, not a set, for the reason 07:97 gives
        `VectorBackend.sweep(live: Callable[[], Iterable[bytes]])` the same shape: the reference
        counts are `asset`, `part` and `cache_index` rows (07:930-935) and reading them needs the
        connection an eager module may not open (INV-17). It is called **once**, inside this method,
        so the mark is taken at a single point in time rather than re-queried per candidate.

        **`forget` is a parameter and not the caller's next statement, and that is the whole
        design.** 07:930-932 fixes the order: "a sweep deletes the file **before** the row so a
        dangling row (recoverable) is the only reachable inconsistency, never a dangling file (a
        leak)". A signature that returned the doomed digests and let the caller delete their rows
        would make the other order available -- and the other order is the one that leaks, because a
        row deleted before its file is a file nothing will ever name again. Here `forget(digest)`
        runs only after `unlink` has returned, per blob, and the caller has no way to invert it.

        A blob whose file is already gone still gets `forget`: that is the dangling row being
        repaired, not an error.
        """
        marked = {bytes(digest) for digest in live()}
        scanned = files_deleted = rows_forgotten = bytes_reclaimed = 0
        for path, digest in self._iter_blobs():
            scanned += 1
            if digest in marked:
                continue
            try:
                size = path.stat().st_size
            except OSError:  # pragma: no cover - vanished under us; still a row to forget
                size = 0
            try:
                path.unlink()
            except FileNotFoundError:
                pass  # already a dangling row; forgetting it below IS the repair
            except OSError:  # pragma: no cover - locked or read-only; the row MUST survive
                continue
            else:
                files_deleted += 1
                bytes_reclaimed += size
            if forget is not None:
                forget(digest)
            rows_forgotten += 1
        return SweepReport(scanned, files_deleted, rows_forgotten, bytes_reclaimed)

    def _iter_blobs(self) -> Iterator[tuple[Path, bytes]]:
        """Every well-named blob under the fanout, with its digest.

        Only `[0-9a-f]{2}` directories and `[0-9a-f]{64}` names are yielded, so `tmp/`,
        `headroom.json` and any foreign file a user dropped in are invisible to the sweep. A sweep
        that deleted what it could not name would be a sweep that deletes a future schema's files.
        """
        if not self._root.is_dir():  # pragma: no cover - the root is checked at construction
            return
        for first in self._iter_hex_dirs(self._root):
            for second in self._iter_hex_dirs(first):
                with os.scandir(second) as entries:
                    for entry in entries:
                        if entry.is_file() and _HEX_64.match(entry.name):
                            yield Path(entry.path), bytes.fromhex(entry.name)

    @staticmethod
    def _iter_hex_dirs(parent: Path) -> Iterator[Path]:
        with os.scandir(parent) as entries:
            for entry in entries:
                if entry.is_dir() and _HEX_2.match(entry.name):
                    yield Path(entry.path)

    # -- integrity ---------------------------------------------------------------------------

    def verify(self, digest: bytes | str) -> bool:
        """Re-hash one blob and say whether it still is what its name claims.

        **A hash collision is not handled and does not need to be, but a content mismatch is**
        (07:920-923). `ow store fsck --cas` re-hashes a sampled `[cache] fsck_sample_frac = 0.01` of
        blobs per run plus every blob a failed `--verify` touched; a mismatch is
        `Diag(OW_INTEGRITY_UNCHECKED)` on the owning `part`, a member of `ABSENCE_BLOCKING_DIAGS`,
        so it degrades a Verdict rather than corrupting a quote. This returns the boolean; the
        `Diag` is L2's and is not constructed here, because `model` is LAZY.
        """
        import hashlib  # noqa: PLC0415 -- use-time, so nothing here runs at import (G17's rule)

        want = _as_digest(digest)
        hasher = hashlib.sha256()
        with self.open(want) as fh:
            while chunk := fh.read(_CHUNK_BYTES):
                hasher.update(chunk)
        return hasher.digest() == want

    def _no_space(self, exc: OSError, staged: Path) -> ResourceLimit:
        """ENOSPC (and EDQUOT) -> `OW_RESOURCE_LIMIT`, naming the knob (07:928-930).

        Any other `OSError` is re-raised unchanged: a permission error is not a resource limit, and
        answering it with "raise `cache.min_free_bytes`" would be a lie in a field whose whole
        contract is to name the knob that clears the error.
        """
        import errno  # noqa: PLC0415 -- use-time, so nothing here runs at import (G17's rule)

        if exc.errno not in (errno.ENOSPC, errno.EDQUOT):
            raise exc
        return ResourceLimit(
            f"out of space writing {staged.name} into {self.tmp_root}",
            limit=_MIN_FREE_BYTES_KEY,
            fix="ow store gc --cas   # then rerun; cas/tmp/ is swept at the next store open",
        )
