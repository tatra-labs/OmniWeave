"""`vector.brute` -- the stdlib `VectorBackend`, and the `vec` sidecar it is the only reader of.

07-store-and-retrieval.md section 3.9 is this module's specification and it is unusually complete:
the DDL is printed, the ceiling is MEASURED rather than assumed, and every derived number is shown.
*"CPython 3.11, 96-byte signatures, XOR + `int.bit_count()` + a 512-entry heap: **200,000
signatures scanned in 81 ms**"* (07:812-813). Everything else in that table -- 2,469 segments/ms,
237 MB/s, 101 ms at the ceiling, 62 rows and 27.2 MB read -- follows from those two numbers, and
this module exists to be the code that measurement describes.

## Why a brute-force scan is the SHIPPED backend and not a placeholder

16:1148 and DP3 settle it: *"v1 ships `vector.brute` plus the 250k refusal and
`vectors = "off"`"*, because F10 found no ANN library that clears G3's three scans and ships pure
wheels for nine cells. The two candidates that declare permissive licences are not in the mined
collection, and the pruned-graph design that is the asset comes with a resident daemon the charter
section 6.11 bans. So the seam is the `omniweave.backends` entry point and the in-tree
implementation is an exhaustive scan whose cost is known to the millisecond.

**The scan is affordable because of the LAYOUT, not because of the arithmetic.** `vseg` holds
CONTIGUOUS SEGMENTS of `VSEG_SIZE = 4096` and never a row per vector, and 07:821 prices the
difference: at the ceiling that is *"62 rows, 27.2 MB"* against 250,000 cursor steps, which is the
mechanism behind the measured 2.3x (1072 ms vs 466 ms per million). A row per vector would be the
same bytes and a different program.

## The four contract obligations, and where each one is discharged here

07:103-113 lists them, *"each because a real system got it wrong"*:

1. **Filter pushdown is real.** `candidates` is applied INSIDE the scan loop, before the heap, so a
   narrowed query ranks only what survived the narrowing. `VecManifest.pushdown` is `True` for this
   backend and that is not a boast: the alternative -- LEANN's post-filter after retrieval with no
   over-fetch -- *"is silent recall loss that presents as absence"*.
2. **Epoch-immutable.** `search()` reads through the connection it was constructed with, and the
   sidecar is ATTACHed once at open; there is no rebuild-in-place path in this backend, so the
   second branch (*"returns `unavailable(rebuilding)`"*) is never taken. It also cannot be taken --
   `search()` returns a `Sequence` with nowhere to put a status, which is D251.
3. **It declares a ceiling and REFUSES above it.** `VEC_BRUTE_MAX = 250_000` SEGMENTS, checked
   before the first `vseg` row is read, raising `OW-S-022`. 07:834: *"the stdlib backend **refuses**
   before running ... so the refusal costs nothing"*, and 12-performance.md:159 is the reason the
   refusal exists at all -- B28 measures the five-Channel warm query at 281 ms against a 250 ms
   ceiling, so the ceiling is a refusal and never a slow path.
4. **recall@10 against exhaustive f32** is `gate_vec_recall.py`'s (07:3392, F9) and is a gate rather
   than a runtime check. What this module owes it is the rerank: `sig -> top-RERANK_N -> f32`.

## Three numbers, and why only one of them is in `limits.py`

`VEC_BRUTE_MAX` is a CEILING -- 01:608, *"a number its own producer is built never to exceed"*,
which is INV-22 and `limits.py`'s own rule -- so it lives in `omniweave_core.limits`
and is imported. `VSEG_SIZE` and
`RERANK_N` are not ceilings: one is a physical layout parameter and the other a rerank depth, and
both are this backend's alone. A different `VectorBackend` has different values for both and the
same `VEC_BRUTE_MAX` would be wrong for it -- which is D252, recorded rather than worked around.

## What this module deliberately does not do

**It opens nothing.** INV-17 puts every `sqlite3.connect` in `store/sqlite.py`, and the sidecar is
reached by ATTACH rather than by a second connection (07:789, *"ATTACHed as `vec`"*), so
`BruteVectors` takes a connection and `sqlite.attach_vec()` is what put `vec` on it. That is also
what makes the join back to `segment` possible inside one snapshot, which 07:1372 calls *"the only
exit from the `vec` sidecar (ST4)"*.

**It registers no entry point.** 18:1708 makes `[retrieval] vec.backend` *"an
`omniweave.backends` entry-point name, selected **by name in config only**"*, and `discovery.py`'s
`BACKEND_GROUP` carries values that name a PACKAGE rather than a class. Wiring a name to this class
is the config and discovery path's work and it has no home yet; until it does, a caller constructs
`BruteVectors` and hands it to `SqliteReader(vectors=...)`. Reported.

**It does not know its own metric.** `VecManifest`'s eleven fields carry `storage`, `sig_bits` and
`dim` and no `metric`; `embed_space.metric` is in the MAIN store (07:641). The rerank computes a dot
product, which IS cosine for the `normalize = 1` space the shipped configuration builds, and says so
rather than reading a main-store column a sidecar-scoped backend has no business joining.

Specified in 07-store-and-retrieval.md sections 1.1, 3.7, 3.9 and 5.2, and 16-roadmap.md:658
(W6.2).
"""

from __future__ import annotations

import heapq
import sqlite3
import sys
from array import array
from typing import TYPE_CHECKING, Final

from omniweave_core.errors import StoreError
from omniweave_core.limits import VEC_BRUTE_MAX
from omniweave_core.store.types import VecManifest

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable, Mapping, Sequence
    from pathlib import Path

__all__ = [
    "RERANK_N",
    "SIDECAR_DDL",
    "VSEG_SIZE",
    "BruteVectors",
    "f32",
    "parse_manifest",
    "sign",
    "to_f32",
    "vec_path",
]


VSEG_SIZE: Final = 4096
"""07:808. How many vectors one `vseg` row holds, and the whole reason the scan is affordable.

At the ceiling this makes `ceil(250_000/4096) = 62` rows and 27.2 MB read (07:821), *"inside
`mmap_size`"*, against 250,000 cursor steps for the row-per-vector layout it replaced -- which is
the mechanism behind the measured 2.3x. Not a `limits.py` entry: it is a layout parameter of THIS
backend, not a ceiling anything is built never to exceed.
"""

RERANK_N: Final = 1000
"""07:808. How deep the signature stage goes before an exact f32 rerank, when one runs at all.

F9 (07:3392) is the open question this number is the subject of: *"Does binary quantisation to
`sig_bits = dim` plus an exact rerank of the top 1,000 hold recall on document segments?"* --
measured by `gate_vec_recall.py` as recall@10 against exhaustive f32 on a fixed 50k fixture, with
`sig_full` only and a smaller ceiling as the answer if it lands below 0.95.
"""

_MEASURED_HEAP: Final = 512
"""The heap size 07:813's measurement was taken with, and a FLOOR here rather than a fixed size.

*"XOR + `int.bit_count()` + a 512-entry heap: 200,000 signatures scanned in 81 ms."* The heap this
backend needs is `k`, or `RERANK_N` when a rerank will follow, and either may be smaller than 512;
taking the maximum keeps the shipped scan no cheaper than the one the 81 ms was measured on, so the
published rate is never an overstatement of what this code does.
"""

_DIGEST_BYTES: Final = 16
"""`segment.content_digest` is `ow128` -- sixteen bytes -- and `vseg.digests` is `n x 16 B`."""

_SIDECAR_SUFFIX: Final = ".vec"

SIDECAR_DDL: Final[tuple[str, ...]] = (
    "CREATE TABLE IF NOT EXISTS vec.vec_manifest (k TEXT PRIMARY KEY, v TEXT NOT NULL)",
    "CREATE TABLE IF NOT EXISTS vec.vseg ("
    "  model_key TEXT NOT NULL, seg_no INTEGER NOT NULL, n INTEGER NOT NULL,"
    "  digests BLOB NOT NULL, sigs BLOB NOT NULL, live BLOB NOT NULL,"
    "  PRIMARY KEY (model_key, seg_no))",
    "CREATE TABLE IF NOT EXISTS vec.vfull ("
    "  model_key TEXT NOT NULL, segment_digest BLOB NOT NULL, v BLOB NOT NULL,"
    "  PRIMARY KEY (model_key, segment_digest)) WITHOUT ROWID",
    "CREATE TABLE IF NOT EXISTS vec.vpending ("
    "  model_key TEXT NOT NULL, segment_digest BLOB NOT NULL, chars INTEGER NOT NULL,"
    "  PRIMARY KEY (model_key, segment_digest)) WITHOUT ROWID",
)
"""07:789-806's four tables, transcribed, with `IF NOT EXISTS` and SCHEMA-QUALIFIED as `vec.`.

Qualified because there is no other way to reach them: the sidecar is ATTACHed (07:789) and an
unqualified `CREATE TABLE` on an attached connection lands in `main`, which would put four sidecar
tables inside the store the sidecar exists to be deletable from.

`IF NOT EXISTS` and not a migration runner: the sidecar is *"[DER] Optional. Deletable."* and has no
generation of its own. 07:2656 makes that explicit -- *"Nothing on the read path depends on the
sweep having happened"* -- and 07:3077 says a moved `index.owstore` rebuilds its vectors. A derived
file that can be deleted at any moment does not get the versioned-migration machinery the store
has; it gets a `CREATE IF NOT EXISTS` and a `corpus_id` that decides whether it is read at all.
"""

_MANIFEST_INT: Final = ("schema", "sig_bits", "dim", "built_at_ns", "rows")
_MANIFEST_FALSE: Final = frozenset({"", "0", "false", "False"})


def f32(blob: bytes) -> array[float]:
    """`vfull.v`'s `dim*4 B f32 LE` (07:801) as floats, byte order made explicit.

    `array("f")` reads NATIVE order and the column is little-endian by declaration, so a
    big-endian host would read every vector as garbage that is still a float and still ranks. The
    swap is a no-op on every machine anyone will run this on and the line is here so the declared
    format and the reader agree by construction rather than by where the tests ran.
    """
    values: array[float] = array("f")
    values.frombytes(blob)
    if sys.byteorder != "little":
        values.byteswap()
    return values


def to_f32(values: Sequence[float]) -> bytes:
    """The inverse of `f32`: floats to `dim*4 B f32 LE`, for whatever builds the sidecar."""
    out: array[float] = array("f", values)
    if sys.byteorder != "little":
        out.byteswap()
    return out.tobytes()


def vec_path(store: Path) -> Path:
    """`index.owstore` -> `index.vec.owstore`, 11-repo-layout's and 07:136's spelling.

    Derived from the store's own path rather than from a constant, because a corpus directory holds
    one store and its two sidecars beside it (07:136, 07:839) and the pairing is positional.
    """
    return store.with_name(store.stem + _SIDECAR_SUFFIX + store.suffix)


def parse_manifest(rows: Mapping[str, str]) -> VecManifest:
    """`vec_manifest`'s `(k, v)` rows as the eleven-field record. THE one home for the mapping.

    `vec_manifest` is a key-value table, so every value arrives as TEXT and the widths and flags are
    parsed here; `reader.py` reads the same table at open to fill `IndexCaps` and calls this rather
    than repeating the field list, because two parsers of one table is the drift INV-21 forbids.

    A missing key takes a zero-shaped default rather than raising: 07:2650's build order rewrites
    `vec_manifest` LAST, so a half-written sidecar is a real state and the reader's job is to make
    it legible. A value that is present and not an integer is a different fact and `int()` raises,
    which the callers catch as `vec_unreadable`.
    """
    numbers = {key: int(rows.get(key, 0)) for key in _MANIFEST_INT}
    return VecManifest(
        corpus_id=rows.get("corpus_id", ""),
        schema=numbers["schema"],
        model_key=rows.get("model_key", ""),
        backend=rows.get("backend", ""),
        backend_version=rows.get("backend_version", ""),
        storage="sig_full" if rows.get("storage") == "sig_full" else "sig_only",
        sig_bits=numbers["sig_bits"],
        dim=numbers["dim"],
        built_at_ns=numbers["built_at_ns"],
        rows=numbers["rows"],
        pushdown=rows.get("pushdown", "0") not in _MANIFEST_FALSE,
    )


def sign(values: Sequence[float], sig_bits: int) -> bytes:
    """One sign bit per dimension, big-endian within each byte. 07:660's binary quantisation.

    *"`sig_bits` **defaults to `dim`** -- one sign bit per dimension is what binary quantisation of
    a normalised vector produces -- so the shipped `bge-m3` space at `dim = 768` has
    `sig_bits = 768` and a **96-byte** signature."* That is the same 96 bytes 07:812's ceiling was
    measured on and the same 112 B/segment 07:1062 prices the sidecar at, so the width is not a
    tuning knob: it is `dim`, and everything downstream is arithmetic on it.

    A non-negative component sets its bit. The choice of which side of zero gets the 1 is
    arbitrary and only has to be the same at build and at query, which is why it is stated here
    rather than left to the caller: two implementations that disagree produce signatures whose
    Hamming distance is `sig_bits - d` instead of `d`, and every ranking inverts with no error.
    """
    if sig_bits <= 0 or sig_bits % 8 or sig_bits > len(values):
        msg = (
            f"sig_bits={sig_bits} does not fit {len(values)} dimensions as whole bytes: a "
            f"signature is one sign bit per dimension (07:660), so it is a multiple of 8 and at "
            f"most `dim`"
        )
        raise StoreError(msg, fix="build the space with sig_bits = dim")
    out = bytearray(sig_bits // 8)
    for index in range(sig_bits):
        if values[index] >= 0.0:
            out[index // 8] |= 0x80 >> (index % 8)
    return bytes(out)


class BruteVectors:
    """The `VectorBackend` 07 section 3.9 measures. Four methods over one ATTACHed sidecar.

    It takes a `sqlite3.Connection` that already carries `vec` and opens nothing itself; see the
    module docstring for why that is INV-17 rather than an inconvenience.

    `model_key` partitions every table, because one sidecar may hold more than one space at a time
    -- 07:2655 has *"the old space's rows ... swept by `VectorBackend.sweep(live)` at the next
    maintenance window"*, which means the two coexist until then.
    """

    def __init__(self, connection: sqlite3.Connection) -> None:
        self._connection = connection

    # -- 1. manifest -------------------------------------------------------

    def manifest(self) -> VecManifest:
        """The sidecar's identity, read fresh. 07:3339's eleven fields through `parse_manifest`."""
        rows = {
            str(key): str(value)
            for key, value in self._connection.execute("SELECT k, v FROM vec.vec_manifest")
        }
        return parse_manifest(rows)

    # -- 2. search ---------------------------------------------------------

    def search(
        self,
        model_key: str,
        q_sig: bytes,
        q_full: bytes | None,
        *,
        k: int,
        candidates: frozenset[bytes] | None,
    ) -> Sequence[tuple[bytes, float]]:
        """The signature scan, the bounded heap, and an exact rerank when `sig_full` allows one.

        Three refusals before a byte is read, in the order that makes each one cheap:

        * **`sig_bits = 0`.** 07:664: *"the stdlib backend refuses such a space outright, because an
          exhaustive f32 scan is what the signature stage exists to avoid"*. There is no cheaper
          scan to fall back to; a space built without a signature stage is a space built for a
          different backend.
        * **a query signature of the wrong width**, which would XOR against a different space's
          bits and rank by nothing.
        * **`VEC_BRUTE_MAX`.** The count is `sum(vseg.n)` over at most 62 rows -- an aggregate over
          the row headers, not a scan of the blobs -- and it counts SWEPT entries too, which makes
          the refusal fire slightly early. That is the fail-expensive direction and it costs
          nothing: 07:834's whole point is that *"the refusal costs nothing"*, and a corpus within a
          rounding error of the ceiling is in the band 07:833 already says to expect
          `UNAVAILABLE(timeout)` from.

        The scan itself is 07:812's: XOR two integers and count the bits. The query signature is
        converted once; each candidate is a slice of the row's contiguous `sigs` blob. `candidates`
        is tested BEFORE the distance, which is obligation (1) -- the filter narrows the set that is
        RANKED and not the set that is returned.

        The score is a similarity in `[0, 1]` (`1 - distance/sig_bits`) so that higher is better,
        which is what `search()`'s `(digest, score)` pairs mean everywhere else. The rerank returns
        a dot product instead, on a different scale; that is deliberate and safe, because the
        semantic Channel reads the ORDER and lifts by rank (07:1511) and never compares a score
        from one backend against a score from another.
        """
        manifest = self.manifest()
        width = self._scan_width(manifest, q_sig)
        self._refuse_above_ceiling(model_key)
        want = max(k, RERANK_N if manifest.storage == "sig_full" else 0, _MEASURED_HEAP)
        query = int.from_bytes(q_sig, "big")
        heap: list[tuple[int, bytes]] = []
        for count, digests, sigs, live in self._connection.execute(
            "SELECT n, digests, sigs, live FROM vec.vseg WHERE model_key = ? ORDER BY seg_no",
            (model_key,),
        ):
            self._scan_row(
                int(count),
                bytes(digests),
                bytes(sigs),
                bytes(live),
                width=width,
                query=query,
                candidates=candidates,
                want=want,
                heap=heap,
            )
        found = sorted((-negated, digest) for negated, digest in heap)
        if manifest.storage == "sig_full" and q_full is not None:
            return self._rerank(model_key, [digest for _d, digest in found], q_full, k)
        return [(digest, 1.0 - distance / manifest.sig_bits) for distance, digest in found[:k]]

    @staticmethod
    def _scan_width(manifest: VecManifest, q_sig: bytes) -> int:
        """The signature width in bytes, or the refusal that stops the scan before it starts."""
        if manifest.sig_bits <= 0:
            msg = (
                "this space has no signature stage (sig_bits = 0) and vector.brute will not run "
                "an exhaustive f32 scan: the signature stage is what that avoids (07:664)"
            )
            raise StoreError(msg, fix="[retrieval] backend = an ANN backend")
        width = manifest.sig_bits // 8
        if len(q_sig) != width:
            msg = (
                f"the query signature is {len(q_sig)} bytes and this space is "
                f"{width} ({manifest.sig_bits} bits): a signature of the wrong width ranks by "
                f"nothing, because every XOR is against a different space's dimensions"
            )
            raise StoreError(msg, fix="re-embed the query in this store's space")
        return width

    def _refuse_above_ceiling(self, model_key: str) -> None:
        """Obligation (3): declare a ceiling and refuse above it. `OW-S-022` (07:834)."""
        row = self._connection.execute(
            "SELECT coalesce(sum(n), 0) FROM vec.vseg WHERE model_key = ?", (model_key,)
        ).fetchone()
        rows = 0 if row is None else int(row[0])
        if rows > VEC_BRUTE_MAX:
            msg = (
                f"this space holds {rows} segments and vector.brute's ceiling is "
                f"{VEC_BRUTE_MAX}: at the measured 2,469 segments/ms the scan alone would be "
                f"{rows // 2469} ms, and an honest refusal beats a query nobody warned you about"
            )
            raise StoreError(msg, fix="[retrieval] backend = an ANN backend")

    @staticmethod
    def _scan_row(
        count: int,
        digests: bytes,
        sigs: bytes,
        live: bytes,
        *,
        width: int,
        query: int,
        candidates: frozenset[bytes] | None,
        want: int,
        heap: list[tuple[int, bytes]],
    ) -> None:
        """One `vseg` row, scanned into the bounded heap. The 81 ms measurement's inner loop.

        07:794 makes `live` a *"ceil(n/8) B bitmap; a swept row clears its bit"*, so a swept entry
        costs one bit test and no XOR -- which is what makes `sweep()` cheap enough to be a
        maintenance-window operation rather than a rewrite.

        The heap holds `(-distance, digest)` so its root is the WORST kept candidate and a new one
        replaces it in `O(log want)`. The digest is in the tuple for the tie-break, which makes the
        result deterministic under equal distances: ST7 needs two runs over one sidecar to agree,
        and Hamming distances over 768 bits tie constantly.
        """
        for index in range(count):
            if not live[index // 8] & (0x80 >> (index % 8)):
                continue
            start = index * _DIGEST_BYTES
            digest = digests[start : start + _DIGEST_BYTES]
            if candidates is not None and digest not in candidates:
                continue
            offset = index * width
            distance = (int.from_bytes(sigs[offset : offset + width], "big") ^ query).bit_count()
            if len(heap) < want:
                heapq.heappush(heap, (-distance, digest))
            elif -heap[0][0] > distance:
                heapq.heapreplace(heap, (-distance, digest))

    def _rerank(
        self, model_key: str, digests: Sequence[bytes], q_full: bytes, k: int
    ) -> list[tuple[bytes, float]]:
        """07:808's `RERANK_N` stage: the signature top-N re-scored against the stored f32 vectors.

        Free precision when the corpus is small enough to scan, which 07:676 says is everywhere the
        stdlib backend serves at all: *"at `dim = 768` the first clause binds first: 250,000
        segments of `sig_full` is 800 MB, so `auto` means `sig_full` everywhere the stdlib backend
        will serve"*.

        A digest with no `vfull` row is dropped rather than kept at its signature score. Mixing the
        two scales in one result would make the ordering depend on which half a hit came from, and a
        `sig_full` space missing a vector is a half-built sidecar, which 07:2081 already reports as
        `coverage = partial`.

        The score is a dot product. For the `normalize = 1` space the shipped configuration builds
        that IS cosine; `VecManifest` carries no `metric`, so this backend states its assumption
        rather than joining `main.embed_space` for a column a sidecar-scoped backend has no
        business reading. D255.
        """
        query = f32(q_full)
        stored = {
            bytes(digest): bytes(vector)
            for digest, vector in self._connection.execute(
                f"SELECT segment_digest, v FROM vec.vfull WHERE model_key = ? "  # noqa: S608
                f"AND segment_digest IN ({','.join('?' * len(digests))})",
                (model_key, *digests),
            )
        }
        scored: list[tuple[float, bytes]] = []
        for digest in digests:
            raw = stored.get(digest)
            if raw is None:
                continue
            other = f32(bytes(raw))
            scored.append((-sum(a * b for a, b in zip(query, other, strict=False)), digest))
        scored.sort()
        return [(digest, -negated) for negated, digest in scored[:k]]

    # -- 3. upsert ---------------------------------------------------------

    def upsert(self, model_key: str, rows: Iterable[tuple[bytes, bytes, bytes | None]]) -> int:
        """`(digest, sig, full)` triples into `vseg` and `vfull`. Returns how many arrived.

        **The `vseg` rows are rebuilt, not appended to.** 07:794-795 requires the digests inside a
        row to be sixteen bytes apiece and SORTED, and the rows to be contiguous
        `VSEG_SIZE` segments, and an append cannot preserve either: a digest that sorts into row 3
        would have to split it. So an upsert reads the existing live entries for this `model_key`,
        merges the new ones over them by digest, and rewrites the whole partition.

        That is O(all) per call and it is the right trade at v1 for a reason 07:2661 states: *"a
        `kill -9` mid-build leaves a consistent partial index"* because `vec_manifest` is written
        last, and the build path (`ow index vectors`) upserts in large batches rather than one
        segment at a time. An incremental layout that kept the sort is a later optimisation with a
        crash story to write; this one has none to write.

        A `full` vector is stored only when it was supplied. `storage` says whether the space HAS
        an f32 stage; this method does not consult it, because a caller that supplies vectors for a
        `sig_only` space is describing a space it is about to promote and the rows are harmless
        until `vec_manifest` says otherwise.
        """
        incoming = {digest: (sig, full) for digest, sig, full in rows}
        if not incoming:
            return 0
        merged = dict(self._live_entries(model_key))
        merged.update(incoming)
        self._connection.execute("DELETE FROM vec.vseg WHERE model_key = ?", (model_key,))
        ordered = sorted(merged.items())
        for seg_no, start in enumerate(range(0, len(ordered), VSEG_SIZE)):
            chunk = ordered[start : start + VSEG_SIZE]
            count = len(chunk)
            live = bytearray((count + 7) // 8)
            for index in range(count):
                live[index // 8] |= 0x80 >> (index % 8)
            self._connection.execute(
                "INSERT INTO vec.vseg(model_key, seg_no, n, digests, sigs, live) "
                "VALUES(?, ?, ?, ?, ?, ?)",
                (
                    model_key,
                    seg_no,
                    count,
                    b"".join(digest for digest, _payload in chunk),
                    b"".join(payload[0] for _digest, payload in chunk),
                    bytes(live),
                ),
            )
        self._connection.executemany(
            "INSERT OR REPLACE INTO vec.vfull(model_key, segment_digest, v) VALUES(?, ?, ?)",
            [
                (model_key, digest, full)
                for digest, (_sig, full) in incoming.items()
                if full is not None
            ],
        )
        return len(incoming)

    def _live_entries(self, model_key: str) -> dict[bytes, tuple[bytes, bytes | None]]:
        """Every unswept `(digest, (sig, None))` currently in `vseg` for this space.

        `full` comes back `None` for all of them and the caller's `dict.update` only overwrites the
        digests it brought, so a rewritten `vseg` never disturbs `vfull`: the two tables are keyed
        independently and `vfull` is `INSERT OR REPLACE`d for the incoming rows alone.
        """
        found: dict[bytes, tuple[bytes, bytes | None]] = {}
        for count, digests, sigs, live in self._connection.execute(
            "SELECT n, digests, sigs, live FROM vec.vseg WHERE model_key = ? ORDER BY seg_no",
            (model_key,),
        ):
            blob_digests, blob_sigs, bitmap = bytes(digests), bytes(sigs), bytes(live)
            width = len(blob_sigs) // int(count) if count else 0
            for index in range(int(count)):
                if not bitmap[index // 8] & (0x80 >> (index % 8)):
                    continue
                offset = index * _DIGEST_BYTES
                found[blob_digests[offset : offset + _DIGEST_BYTES]] = (
                    blob_sigs[index * width : (index + 1) * width],
                    None,
                )
        return found

    # -- 4. sweep ----------------------------------------------------------

    def sweep(self, live: Callable[[], Iterable[bytes]]) -> int:
        """Clear the `live` bit of every entry the store no longer holds. Returns how many.

        `live` is a CALLABLE returning the digests rather than the set itself, and the shape is the
        one `blobs.py` already uses for the same reason: the caller must be able to stream a set
        that does not fit in memory, and the backend must be able to decide when to materialise it.
        This backend materialises it once, because it needs membership tests against every entry.

        Clearing a bit and not deleting a row is what keeps the layout contiguous: 07:797 calls
        `live` *"ceil(n/8) B bitmap; a swept row clears its bit"*, and a swept entry then costs one
        bit test and no XOR on every later scan. The row is reclaimed at the next `upsert`, which
        rewrites the partition anyway.

        Nothing on the read path depends on this having run (07:2656). A digest still marked live
        whose segment is gone is dropped by the Channel's join back to `segment`, which is why the
        sidecar is deletable and why this is a maintenance-window operation rather than a
        transaction the write path waits on.
        """
        keep = frozenset(live())
        cleared = 0
        updates: list[tuple[bytes, str, int]] = []
        for model_key, seg_no, count, digests, bitmap in self._connection.execute(
            "SELECT model_key, seg_no, n, digests, live FROM vec.vseg ORDER BY model_key, seg_no"
        ):
            blob, bits = bytes(digests), bytearray(bitmap)
            changed = False
            for index in range(int(count)):
                mask = 0x80 >> (index % 8)
                if not bits[index // 8] & mask:
                    continue
                offset = index * _DIGEST_BYTES
                if blob[offset : offset + _DIGEST_BYTES] in keep:
                    continue
                bits[index // 8] &= ~mask & 0xFF
                cleared += 1
                changed = True
            if changed:
                updates.append((bytes(bits), str(model_key), int(seg_no)))
        self._connection.executemany(
            "UPDATE vec.vseg SET live = ? WHERE model_key = ? AND seg_no = ?", updates
        )
        return cleared
