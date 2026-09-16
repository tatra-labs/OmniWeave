"""`store/vectors.py` against a REAL `vec` sidecar, because every claim it makes is about bytes.

The sidecar is four tables and three blobs, and the blobs are where the design lives: `vseg.digests`
is `n x 16 B` sorted, `vseg.sigs` is `n x (sig_bits/8) B` in the same order, and `vseg.live` is
`ceil(n/8) B`. A test against a mock would assert the method names and nothing about the layout the
measured 81 ms depends on, so these build the tables and read them back.

`import sqlite3` is TID251's test exception, taken for the same reason `test_store_reader.py` takes
it: the sidecar IS SQLite (07:149, *"Both sidecars are SQLite, not raw files"*) and a fixture that
could not write it could only test the backend against itself.

Specified in 07-store-and-retrieval.md sections 1.1, 3.7 and 3.9, and 16-roadmap.md:658 (W6.2).
"""

from __future__ import annotations

import sqlite3  # noqa: TID251 -- see the module docstring: the fixtures write a REAL sidecar.
from typing import TYPE_CHECKING

import pytest
from omniweave_core.errors import StoreError
from omniweave_core.store import VectorBackend
from omniweave_core.store import vectors as vec

if TYPE_CHECKING:
    from collections.abc import Sequence
    from pathlib import Path

DIM = 8
"""Eight dimensions, so a signature is ONE byte and a Hamming distance is readable in a test.

The shipped space is `dim = 768` and 96 bytes (07:660), and nothing here depends on the width --
`sign()` takes `sig_bits` and the scan slices by `sig_bits // 8`. Eight is the smallest width that
is a whole byte, which is what makes `0xF0` a distance of four from `0xFF` by inspection.
"""

MANIFEST: dict[str, str] = {
    "corpus_id": "c1",
    "schema": "1",
    "model_key": "m/1",
    "backend": "vector.brute",
    "backend_version": "1",
    "storage": "sig_only",
    "sig_bits": str(DIM),
    "dim": str(DIM),
    "built_at_ns": "7",
    "rows": "0",
    "pushdown": "1",
}


@pytest.fixture
def sidecar(tmp_path: Path) -> sqlite3.Connection:
    """A connection with an empty `vec` sidecar ATTACHed, and the DDL the module ships applied.

    ATTACHed rather than opened as the main schema, because that is the only way the backend is
    ever reached: 07:789 says `index.vec.owstore` is *"ATTACHed as `vec`"*, and every statement in
    the module is written `vec.<table>` for that reason.
    """
    connection = sqlite3.connect(":memory:", isolation_level=None)
    connection.execute("ATTACH DATABASE ? AS vec", (str(tmp_path / "index.vec.owstore"),))
    for statement in vec.SIDECAR_DDL:
        connection.execute(statement)
    connection.executemany(
        "INSERT INTO vec.vec_manifest(k, v) VALUES(?, ?)", list(MANIFEST.items())
    )
    return connection


def _digest(n: int) -> bytes:
    """A 16-byte `segment.content_digest`, big-endian so int order and byte order agree."""
    return n.to_bytes(16, "big")


def _set(connection: sqlite3.Connection, key: str, value: str) -> None:
    connection.execute("INSERT OR REPLACE INTO vec.vec_manifest(k, v) VALUES(?, ?)", (key, value))


def _rows(
    connection: sqlite3.Connection,
) -> list[tuple[int, int, bytes, bytes, bytes]]:
    return [
        (int(seg_no), int(n), bytes(d), bytes(s), bytes(live))
        for seg_no, n, d, s, live in connection.execute(
            "SELECT seg_no, n, digests, sigs, live FROM vec.vseg ORDER BY seg_no"
        )
    ]


# ---------------------------------------------------------------------------------------------
# sign() -- one bit per dimension
# ---------------------------------------------------------------------------------------------


def test_a_signature_is_one_sign_bit_per_dimension() -> None:
    """07:660: *"one sign bit per dimension is what binary quantisation of a normalised vector
    produces"*, so `dim = 768` gives `sig_bits = 768` and a **96-byte** signature.

    Ninety-six is the width 07:812's ceiling was measured on and the 112 B/segment 07:1062 prices
    the sidecar at, so it is arithmetic on `dim` and never a tuning knob.
    """
    assert vec.sign([1.0] * 8, 8) == b"\xff"
    assert vec.sign([1.0, 1.0, 1.0, 1.0, -1.0, -1.0, -1.0, -1.0], 8) == b"\xf0"
    assert vec.sign([-1.0] * 8, 8) == b"\x00"
    assert len(vec.sign([1.0] * 768, 768)) == 96


def test_a_signature_width_that_is_not_whole_bytes_is_refused() -> None:
    """A width that is not a multiple of 8 leaves a partial byte whose spare bits are neither set
    nor absent, and a width above `dim` reads past the vector -- both rank by something that is not
    the vector."""
    with pytest.raises(StoreError, match="whole bytes"):
        vec.sign([1.0] * 8, 12)
    with pytest.raises(StoreError, match="whole bytes"):
        vec.sign([1.0] * 8, 16)


# ---------------------------------------------------------------------------------------------
# upsert() -- the contiguous layout the 81 ms depends on
# ---------------------------------------------------------------------------------------------


def _upsert(connection: sqlite3.Connection, pairs: Sequence[tuple[int, int]]) -> vec.BruteVectors:
    """`(digest byte, signature byte)` pairs into the sidecar."""
    backend = vec.BruteVectors(connection)
    backend.upsert(
        MANIFEST["model_key"],
        [(_digest(d), bytes([s]), None) for d, s in pairs],
    )
    return backend


def test_vseg_holds_contiguous_segments_and_never_a_row_per_vector(
    sidecar: sqlite3.Connection,
) -> None:
    """`VSEG_SIZE = 4096` (07:808), and 07:821 prices the difference it makes.

    At the ceiling the layout is *"62 rows, 27.2 MB"* against 250,000 cursor steps, which is *"the
    mechanism behind the measured 2.3x (1072 ms vs 466 ms per million)"*. `VSEG_SIZE + 1` vectors
    is the smallest input that proves the chunking runs at all.
    """
    _upsert(sidecar, [(i, i % 256) for i in range(vec.VSEG_SIZE + 1)])
    rows = _rows(sidecar)
    assert [seg_no for seg_no, *_rest in rows] == [0, 1]
    assert [n for _s, n, *_rest in rows] == [vec.VSEG_SIZE, 1]
    assert len(rows[0][2]) == vec.VSEG_SIZE * 16
    assert len(rows[0][4]) == vec.VSEG_SIZE // 8


def test_the_digests_inside_a_row_are_sorted_and_the_sigs_are_in_the_same_order(
    sidecar: sqlite3.Connection,
) -> None:
    """07:794-796 gives the two blobs one comment each: the digests are sixteen bytes
    apiece and SORTED, and the signatures are `sig_bits/8` bytes apiece in the SAME ORDER.

    Same order is what makes the scan a slice rather than a lookup: index `i` of `digests` and
    index `i` of `sigs` are one entry, and nothing else joins them.
    """
    _upsert(sidecar, [(9, 0x0F), (3, 0xF0), (7, 0xFF)])
    ((_seg_no, count, digests, sigs, live),) = _rows(sidecar)
    assert count == 3
    assert [digests[i * 16 : i * 16 + 16] for i in range(3)] == [
        _digest(3),
        _digest(7),
        _digest(9),
    ]
    assert sigs == bytes([0xF0, 0xFF, 0x0F])
    assert live == b"\xe0"


def test_an_upsert_merges_over_the_partition_and_keeps_it_sorted(
    sidecar: sqlite3.Connection,
) -> None:
    """The rows are rebuilt and not appended to, because both invariants are positional.

    A digest that sorts into the middle of an existing row cannot be appended anywhere without
    breaking *"sorted"*, so the partition is read, merged and rewritten. The second upsert here
    replaces one signature and inserts one digest between two existing ones.
    """
    backend = _upsert(sidecar, [(1, 0x01), (5, 0x05)])
    backend.upsert(
        MANIFEST["model_key"], [(_digest(3), b"\x03", None), (_digest(5), b"\x55", None)]
    )
    ((_seg_no, count, digests, sigs, _live),) = _rows(sidecar)
    assert count == 3
    assert [digests[i * 16 : i * 16 + 16] for i in range(3)] == [
        _digest(1),
        _digest(3),
        _digest(5),
    ]
    assert sigs == bytes([0x01, 0x03, 0x55])


# ---------------------------------------------------------------------------------------------
# search() -- XOR, bit_count, and a bounded heap
# ---------------------------------------------------------------------------------------------


def test_search_ranks_by_hamming_distance_and_scores_it_as_a_similarity(
    sidecar: sqlite3.Connection,
) -> None:
    """07:812-813's inner loop: *"XOR + `int.bit_count()` + a 512-entry heap"*.

    Against `0xFF`: `0xFF` is 0 bits away, `0xF0` is 4 and `0x00` is 8. The score is
    `1 - distance/sig_bits`, so higher is better -- which is what `(digest, score)` means at every
    other `VectorBackend` too, and the semantic Channel never compares one backend's scores with
    another's anyway.
    """
    backend = _upsert(sidecar, [(1, 0xFF), (2, 0xF0), (3, 0x00)])
    found = backend.search(MANIFEST["model_key"], b"\xff", None, k=10, candidates=None)
    assert [digest for digest, _score in found] == [_digest(1), _digest(2), _digest(3)]
    assert [score for _digest, score in found] == [1.0, 0.5, 0.0]


def test_the_candidate_set_narrows_the_set_that_is_ranked(sidecar: sqlite3.Connection) -> None:
    """Contract obligation (1) (07:104-107), from inside the backend.

    *"`candidates` narrows **before** ranking, tested at 0.01 selectivity. LEANN post-filters
    metadata after ANN retrieval with no over-fetch, which is silent recall loss that presents as
    absence."* The nearest vector is excluded from the set, and the result is the next two rather
    than a shorter list with a hole in it -- which is the whole difference between narrowing before
    and filtering after.
    """
    backend = _upsert(sidecar, [(1, 0xFF), (2, 0xF0), (3, 0x00)])
    found = backend.search(
        MANIFEST["model_key"],
        b"\xff",
        None,
        k=2,
        candidates=frozenset({_digest(2), _digest(3)}),
    )
    assert [digest for digest, _score in found] == [_digest(2), _digest(3)]


def test_search_honours_k(sidecar: sqlite3.Connection) -> None:
    """`k` bounds what comes back; the heap is sized above it so the scan is never cheaper than
    the one 07:813's 81 ms was measured on."""
    backend = _upsert(sidecar, [(1, 0xFF), (2, 0xF0), (3, 0x00)])
    assert len(backend.search(MANIFEST["model_key"], b"\xff", None, k=2, candidates=None)) == 2


def test_equal_distances_break_by_digest_so_two_runs_agree(sidecar: sqlite3.Connection) -> None:
    """ST7 needs two runs over one sidecar to return the same order, and Hamming distances over
    768 bits tie constantly -- so the heap holds `(-distance, digest)` and the digest decides."""
    backend = _upsert(sidecar, [(9, 0xF0), (1, 0xF0), (5, 0xF0)])
    found = backend.search(MANIFEST["model_key"], b"\xff", None, k=3, candidates=None)
    assert [digest for digest, _score in found] == [_digest(1), _digest(5), _digest(9)]


# ---------------------------------------------------------------------------------------------
# The three refusals
# ---------------------------------------------------------------------------------------------


def test_the_ceiling_is_a_refusal_taken_before_the_scan(
    sidecar: sqlite3.Connection, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Contract obligation (3) and `OW-S-022` (07:834).

    *"the stdlib backend **refuses** before running, `OW-S-022`, so the refusal costs nothing"*,
    and 12-performance.md:159 is why it exists: B28 measures the five-Channel warm query at 281 ms
    against a 250 ms ceiling, so `VEC_BRUTE_MAX` is a refusal and never a slow path. The constant
    is moved rather than the corpus grown, because 250,001 vectors would make this suite minutes
    long and the arithmetic under test is the shipped one either way.
    """
    backend = _upsert(sidecar, [(1, 0xFF), (2, 0xF0)])
    monkeypatch.setattr(vec, "VEC_BRUTE_MAX", 1)
    with pytest.raises(StoreError, match="ceiling"):
        backend.search(MANIFEST["model_key"], b"\xff", None, k=1, candidates=None)


def test_a_space_with_no_signature_stage_is_refused_outright(
    sidecar: sqlite3.Connection,
) -> None:
    """07:664: *"`sig_bits = 0` means the space is `sig_full` with no signature stage and
    `VEC_BRUTE_MAX` does not apply to it; the stdlib backend refuses such a space outright, because
    an exhaustive f32 scan is what the signature stage exists to avoid."*"""
    backend = _upsert(sidecar, [(1, 0xFF)])
    _set(sidecar, "sig_bits", "0")
    with pytest.raises(StoreError, match="no signature stage"):
        backend.search(MANIFEST["model_key"], b"\xff", None, k=1, candidates=None)


def test_a_query_signature_of_the_wrong_width_is_refused(sidecar: sqlite3.Connection) -> None:
    """A signature from another space XORs against different dimensions, so it ranks by nothing --
    and every score it produces is a float in the right range, which is the failure mode that has
    no symptom."""
    backend = _upsert(sidecar, [(1, 0xFF)])
    with pytest.raises(StoreError, match="wrong width"):
        backend.search(MANIFEST["model_key"], b"\xff\xff", None, k=1, candidates=None)


# ---------------------------------------------------------------------------------------------
# sig_full -- the rerank
# ---------------------------------------------------------------------------------------------


def _sig_full(connection: sqlite3.Connection) -> vec.BruteVectors:
    """A `sig_full` space whose f32 order DISAGREES with its signature order.

    Vector `1` is the nearer signature (identical to the query) and the smaller dot product;
    vector `2` is four bits away and twenty times the magnitude. So the signature stage ranks
    `1, 2` and the exact rerank ranks `2, 1`, and a test asserting either one is asserting which
    stage produced the answer.
    """
    _set(connection, "storage", "sig_full")
    backend = vec.BruteVectors(connection)
    backend.upsert(
        MANIFEST["model_key"],
        [
            (_digest(1), vec.sign([0.1] * 8, 8), vec.to_f32([0.1] * 8)),
            (
                _digest(2),
                vec.sign([5.0, 5.0, 5.0, 5.0, -0.1, -0.1, -0.1, -0.1], 8),
                vec.to_f32([5.0, 5.0, 5.0, 5.0, -0.1, -0.1, -0.1, -0.1]),
            ),
        ],
    )
    return backend


def test_sig_full_reranks_the_signature_top_n_against_the_stored_vectors(
    sidecar: sqlite3.Connection,
) -> None:
    """07:808's `RERANK_N = 1000`, and F9 (07:3392) is the open question it is the subject of.

    07:676 says the rerank is the normal case rather than the exception: *"at `dim = 768` the first
    clause binds first ... so `auto` means `sig_full` everywhere the stdlib backend will serve at
    all"* -- reranking is free precision when the corpus is small enough to scan.
    """
    backend = _sig_full(sidecar)
    query = vec.to_f32([1.0] * 8)
    signature_only = backend.search(MANIFEST["model_key"], b"\xff", None, k=2, candidates=None)
    reranked = backend.search(MANIFEST["model_key"], b"\xff", query, k=2, candidates=None)
    assert [digest for digest, _score in signature_only] == [_digest(1), _digest(2)]
    assert [digest for digest, _score in reranked] == [_digest(2), _digest(1)]


def test_a_hit_with_no_stored_vector_is_dropped_rather_than_kept_at_its_signature_score(
    sidecar: sqlite3.Connection,
) -> None:
    """Mixing the two scales in one result would make the order depend on which stage a hit came
    from. A `sig_full` space missing a vector is a half-built sidecar, which 07:2081 already
    reports as `coverage = partial`."""
    backend = _sig_full(sidecar)
    sidecar.execute("DELETE FROM vec.vfull WHERE segment_digest = ?", (_digest(2),))
    found = backend.search(
        MANIFEST["model_key"], b"\xff", vec.to_f32([1.0] * 8), k=2, candidates=None
    )
    assert [digest for digest, _score in found] == [_digest(1)]


# ---------------------------------------------------------------------------------------------
# sweep() -- a bit, not a row
# ---------------------------------------------------------------------------------------------


def test_a_swept_entry_clears_its_bit_and_disappears_from_the_scan(
    sidecar: sqlite3.Connection,
) -> None:
    """07:797: *"live BLOB NOT NULL, -- ceil(n/8) B bitmap; a swept row clears its bit"*.

    A bit and not a row, because the layout is positional: deleting an entry would resort the
    partition, and 07:2655 makes the sweep a maintenance-window operation the write path never
    waits on. A swept entry then costs one bit test and no XOR on every later scan, and the row is
    reclaimed at the next `upsert`, which rewrites the partition anyway.
    """
    backend = _upsert(sidecar, [(1, 0xFF), (2, 0xF0), (3, 0x00)])
    cleared = backend.sweep(lambda: [_digest(2), _digest(3)])
    assert cleared == 1
    ((_seg_no, count, _digests, _sigs, live),) = _rows(sidecar)
    assert count == 3
    assert live == b"\x60"
    found = backend.search(MANIFEST["model_key"], b"\xff", None, k=10, candidates=None)
    assert [digest for digest, _score in found] == [_digest(2), _digest(3)]


def test_a_sweep_that_clears_nothing_writes_nothing(sidecar: sqlite3.Connection) -> None:
    """*"Nothing on the read path depends on the sweep having happened"* (07:2656), so a sweep with
    nothing to do is not a write -- which is what lets it run in a maintenance window against a
    store other readers are using."""
    backend = _upsert(sidecar, [(1, 0xFF), (2, 0xF0)])
    before = _rows(sidecar)
    assert backend.sweep(lambda: [_digest(1), _digest(2)]) == 0
    assert _rows(sidecar) == before


# ---------------------------------------------------------------------------------------------
# manifest(), the Protocol, and the path
# ---------------------------------------------------------------------------------------------


def test_the_manifest_is_the_eleven_fields_of_the_key_value_table(
    sidecar: sqlite3.Connection,
) -> None:
    """07:3339-3348's eleven, parsed once in `parse_manifest` and read by two callers.

    `store/reader.py` reads the same table at open to fill `IndexCaps`; two parsers of one `(k, v)`
    schema is the drift INV-21 forbids, so the field list has one home.
    """
    manifest = vec.BruteVectors(sidecar).manifest()
    assert manifest.corpus_id == "c1"
    assert manifest.model_key == "m/1"
    assert manifest.backend == "vector.brute"
    assert manifest.storage == "sig_only"
    assert manifest.sig_bits == DIM
    assert manifest.pushdown is True


def test_a_half_written_manifest_parses_rather_than_raising() -> None:
    """07:2650's build order rewrites `vec_manifest` LAST, so a half-written sidecar is a real
    state and the reader's job is to make it legible. A key that is PRESENT and not an integer is
    a different fact and raises, which the callers report as `vec_unreadable`."""
    assert vec.parse_manifest({}).sig_bits == 0
    assert vec.parse_manifest({}).pushdown is False
    with pytest.raises(ValueError, match="invalid literal"):
        vec.parse_manifest({"dim": "not a number"})


def test_brute_vectors_is_a_vector_backend(sidecar: sqlite3.Connection) -> None:
    """The seam is the Protocol (07:86-92), so the in-tree backend is checked against it by name.

    `VectorBackend` is not `runtime_checkable` -- none of the store's Protocols is -- so this
    compares the four method names rather than calling `isinstance`, which for a non-runtime
    Protocol would be a `TypeError` and for a runtime one would check names and not signatures
    anyway.
    """
    declared = {name for name in vars(VectorBackend) if not name.startswith("_")}
    assert declared == {"manifest", "upsert", "search", "sweep"}
    backend = vec.BruteVectors(sidecar)
    for name in declared:
        assert callable(getattr(backend, name)), f"BruteVectors has no {name}"


def test_the_sidecar_sits_beside_the_store_it_is_derived_from(tmp_path: Path) -> None:
    """07:136's tree: `index.vec.owstore` beside `index.owstore`, so the pairing is positional and
    a moved store finds no sidecar and rebuilds (07:3077)."""
    assert vec.vec_path(tmp_path / "index.owstore").name == "index.vec.owstore"
