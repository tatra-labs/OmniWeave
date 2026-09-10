"""`omniweave_core.blobs` -- the CAS write protocol, its two sweeps and `part` retention.

The tests outweigh the code here, and 16-roadmap.md:419 says why: retention is load-bearing in five
places (INV-10, X8's three re-read branches, Q-G6, SV13 and the storage projection), and every one
of the four write steps exists because the obvious three-step version has a named failure
(07-store-and-retrieval.md:904-909). A test that asserts only "the bytes came back" would pass
against an implementation with none of the four properties, so each step is asserted **by observing
the filesystem at the moment the step runs**, not by its result.

Specified in 07-store-and-retrieval.md section 3.11 (:902-940), 08-runtime.md section 4.7(a)
(:1489-1497), 03-document-model.md sections 7.2 and 13.1, and 14-security.md section 2.3.
"""

from __future__ import annotations

import ast
import errno
import hashlib
import io
import json
import os
import subprocess  # noqa: TID251 -- see `test_importing_blobs_loads_no_sqlite3...` below.
import sys
from pathlib import Path

import pytest
from omniweave_core.blobs import (
    CAS_SCHEME,
    CITABLE_DECLARED_ORIGIN_SPANS,
    FANOUT_DEPTH,
    FANOUT_WIDTH,
    HEADROOM_FILENAME,
    NO_SPACE_DEGRADATION_KIND,
    REVERIFIABLE_OS_KINDS,
    SHA256_BYTES,
    BlobStore,
    Headroom,
    digests_of,
    format_ref,
    parse_ref,
    ref_relative_path,
    retains_part,
)
from omniweave_core.config import KEYS
from omniweave_core.errors import ResourceLimit, StoreError, UsageError
from omniweave_core.limits import MAX_ASSET_BYTES

# The nine LAZY names, verbatim from 11-repo-layout.md section 1.3, as
# tests/unit/test_core_eager_surface.py spells them.
LAZY = (
    "model",
    "store",
    "archive",
    "retrieve",
    "answer",
    "out",
    "host",
    "toolchain",
    "modelserver",
)


@pytest.fixture
def store(tmp_path: Path) -> BlobStore:
    """A `BlobStore` over an existing `cas/`, which is the only kind it will open."""
    root = tmp_path / "cas"
    root.mkdir()
    return BlobStore(root)


def sha256_of(payload: bytes) -> bytes:
    return hashlib.sha256(payload).digest()


def _keep_the_file(self: Path, missing_ok: bool = False) -> None:
    """Stand in for `Path.unlink` so a modelled SIGKILL leaves its staged file behind."""


# ---------------------------------------------------------------------------
# 1. The `cas://ab/cd/<sha256>` reference grammar.
# ---------------------------------------------------------------------------


def test_a_reference_round_trips_from_digest_to_string_and_back() -> None:
    digest = sha256_of(b"round trip")
    ref = format_ref(digest)
    assert ref == f"{CAS_SCHEME}{digest.hex()[:2]}/{digest.hex()[2:4]}/{digest.hex()}"
    assert parse_ref(ref) == digest


def test_a_reference_round_trips_from_the_hex_spelling_too() -> None:
    hexed = sha256_of(b"either spelling").hex()
    assert parse_ref(format_ref(hexed)) == bytes.fromhex(hexed)


def test_the_relative_path_is_slash_separated_on_every_platform() -> None:
    # It is stored in a row and read on another machine, so it is never the host's separator.
    assert "\\" not in str(ref_relative_path(sha256_of(b"x")))
    assert len(ref_relative_path(sha256_of(b"x")).parts) == FANOUT_DEPTH + 1


def test_the_two_level_fanout_is_two_directories_of_two_hex_characters() -> None:
    digest = sha256_of(b"fanout")
    first, second, name = ref_relative_path(digest).parts
    assert len(first) == FANOUT_WIDTH
    assert len(second) == FANOUT_WIDTH
    assert name == digest.hex()
    assert first + second == name[: 2 * FANOUT_WIDTH]


def test_the_fanout_arithmetic_the_docstring_records_is_the_arithmetic() -> None:
    """At 10M blobs a directory holds ~150 entries (07:917-919)."""
    directories = (16**FANOUT_WIDTH) ** FANOUT_DEPTH
    assert directories == 65_536
    assert 145 <= 10_000_000 / directories <= 155


@pytest.mark.parametrize(
    "bad",
    [
        "cas://../../etc/passwd",
        "cas://%2e%2e/%2e%2e/etc/passwd",
        "cas://%2E%2E%2F%2E%2E%2Fetc%2Fpasswd",
        "cas:///etc/passwd",
        "cas://C:/Windows/win.ini",
        "cas://ab/cd/../../../../etc/passwd",
        "cas://ab/cd/CON",
        "cas://ab/cd/report.docx:evil",
        "cas://ab/cd/" + "0" * 63,
        "cas://ab/cd/" + "0" * 65,
        "cas://ab/cd/" + "0" * 63 + "G",
        "cas://ab/cd/" + "AB" * 32,
        "cas://ab/" + "0" * 64,
        "cas://ab/cd/ef/" + "0" * 64,
        "file:///ab/cd/" + "0" * 64,
        "",
        "cas://",
    ],
)
def test_a_malformed_reference_is_refused_rather_than_coerced(bad: str) -> None:
    """A refusal, never a repair: 14-security.md:293's `OW_PATH_OUTSIDE_ROOTS` discipline."""
    with pytest.raises(UsageError):
        parse_ref(bad)


def test_a_reference_whose_fanout_disagrees_with_its_own_digest_is_refused() -> None:
    """The shape a hand-edited row takes: the directories say one thing, the name another."""
    digest = sha256_of(b"disagree")
    hexed = digest.hex()
    forged = f"{CAS_SCHEME}ff/{hexed[2:4]}/{hexed}"
    assert forged != format_ref(digest)
    with pytest.raises(UsageError, match="but its digest says"):
        parse_ref(forged)


def test_a_reference_is_refused_when_it_is_not_even_a_string() -> None:
    with pytest.raises(UsageError, match="is a str"):
        parse_ref(b"cas://ab/cd/" + b"0" * 64)  # type: ignore[arg-type]


def test_a_digest_of_the_wrong_width_is_refused_by_the_formatter() -> None:
    with pytest.raises(UsageError, match=f"{SHA256_BYTES} bytes"):
        format_ref(b"\x00" * 31)
    with pytest.raises(UsageError, match="64 lowercase hex"):
        format_ref("deadbeef")
    with pytest.raises(UsageError, match="bytes or 64-char hex"):
        format_ref(17)  # type: ignore[arg-type]


def test_digests_of_refuses_the_whole_batch_on_the_first_bad_reference() -> None:
    good = format_ref(sha256_of(b"good"))
    assert digests_of([good, good]) == (sha256_of(b"good"), sha256_of(b"good"))
    with pytest.raises(UsageError):
        digests_of([good, "cas://../../etc/passwd"])


# ---------------------------------------------------------------------------
# 2. `retain_parts`. 07 section 8.1 (:2539-2543), with 02:486 as the worked case.
# ---------------------------------------------------------------------------


def test_the_three_retention_policies_are_configs_three_and_no_others() -> None:
    """INV-21: the policy names have one home, `config.KEYS` (config.py:714-719)."""
    assert KEYS["store.retain_parts"].choices == ("always", "when_citable", "never")
    assert KEYS["store.retain_parts"].default == "when_citable"


def test_an_unknown_retention_policy_is_refused_rather_than_treated_as_never() -> None:
    with pytest.raises(UsageError, match="retain_parts is one of"):
        retains_part("sometimes", declared_origin_span="exact")


@pytest.mark.parametrize("declared", ["exact", "normalized", "none"])
@pytest.mark.parametrize("os_kind", [None, "bytes", "nodepath", "glyphs", "pixels", "none"])
def test_always_retains_everything_and_never_retains_nothing(
    declared: str, os_kind: str | None
) -> None:
    """The two total policies are total: neither reads either axis (07:2539)."""
    assert retains_part("always", declared_origin_span=declared, os_kind=os_kind) is True
    assert retains_part("never", declared_origin_span=declared, os_kind=os_kind) is False


def test_never_is_what_makes_quote_verbatim_unreachable() -> None:
    """INV-10 x F32: under `never` the tier is empty and that is disclosed, not hidden.

    01-principles.md:761-766 and 07:2541-2543. The assertion is that no combination of the other
    two axes can retain a part under `never` -- because `verbatim` needs a retained part, so a
    single leak here would make the disclosure false.
    """
    for declared in ("exact", "normalized", "none"):
        for os_kind in (None, *sorted(REVERIFIABLE_OS_KINDS), "pixels", "none"):
            assert retains_part("never", declared_origin_span=declared, os_kind=os_kind) is False


@pytest.mark.parametrize("declared", sorted(CITABLE_DECLARED_ORIGIN_SPANS))
def test_when_citable_reads_the_declared_card_and_retains_exact_and_normalized(
    declared: str,
) -> None:
    """07:2540-2541's `iff`, over the card, with no `os_kind` in evidence."""
    assert retains_part("when_citable", declared_origin_span=declared) is True


def test_when_citable_does_not_retain_a_card_declaring_none() -> None:
    """The office path at release 1: `origin_span = "none"`, so no part is retained (07:2530)."""
    assert retains_part("when_citable", declared_origin_span="none") is False


def test_the_worked_case_at_02_486_retains_a_glyphs_part() -> None:
    """02:486's cell: retained because `origin_span='glyphs'` satisfies `when_citable`."""
    assert retains_part("when_citable", declared_origin_span="exact", os_kind="glyphs") is True


@pytest.mark.parametrize("os_kind", sorted(REVERIFIABLE_OS_KINDS))
def test_when_citable_retains_a_part_on_each_of_inv_10s_three_re_read_branches(
    os_kind: str,
) -> None:
    """X8's three branches: `bytes`, `nodepath`, `glyphs` (01-principles.md:310-312)."""
    assert retains_part("when_citable", declared_origin_span="exact", os_kind=os_kind) is True


@pytest.mark.parametrize("os_kind", ["pixels", "none"])
def test_when_citable_does_not_retain_a_part_that_can_never_be_re_read(os_kind: str) -> None:
    """`pixels` and `none` "can never reach it: there is nothing to re-read" (03:1652).

    This is the narrowing the module's docstring reports as a deviation from 07:2540's bare `iff`.
    It is safe in the only direction that matters -- it can never withhold bytes a `verbatim` claim
    would have needed -- and it is what stops item 5 of the five, the storage projection, paying
    ~71 GB (12:355) for bytes with no possible consumer.
    """
    assert retains_part("when_citable", declared_origin_span="exact", os_kind=os_kind) is False


def test_the_three_re_verifiable_branches_are_exactly_inv_10s_three() -> None:
    assert sorted(REVERIFIABLE_OS_KINDS) == ["bytes", "glyphs", "nodepath"]
    assert sorted(CITABLE_DECLARED_ORIGIN_SPANS) == ["exact", "normalized"]


def test_the_two_retention_axes_are_different_closed_domains() -> None:
    """The contradiction the predicate's docstring reports, asserted so it cannot be forgotten.

    `Capabilities.origin_span` is `{none, normalized, exact}` (model/block.py:304);
    `origin_span_kind` is `{bytes, nodepath, glyphs, pixels, none}` (model/enums.py:283-288).
    02-architecture.md:486 names a member of the second while citing a rule about the first.
    """
    from omniweave_core.model.enums import OsKind  # noqa: PLC0415 -- LAZY, so imported in-test

    kinds = {k.value for k in OsKind}
    assert sorted(kinds) == ["bytes", "glyphs", "nodepath", "none", "pixels"]
    assert kinds > REVERIFIABLE_OS_KINDS
    assert CITABLE_DECLARED_ORIGIN_SPANS.isdisjoint(kinds - {"none"})


# ---------------------------------------------------------------------------
# 3. The four-step write protocol, asserted step by step.
# ---------------------------------------------------------------------------


def test_put_returns_the_sha256_of_the_stream_and_stores_it_at_the_fanout_path(
    store: BlobStore,
) -> None:
    payload = b"the name IS the digest"
    digest = store.put(io.BytesIO(payload))
    assert digest == sha256_of(payload)
    assert store.path(digest) == store.root / digest.hex()[:2] / digest.hex()[2:4] / digest.hex()
    assert store.path(digest).read_bytes() == payload
    assert store.has(digest)


def test_the_temp_file_is_inside_cas_so_step_three_is_never_cross_device(
    store: BlobStore,
) -> None:
    """07:911-914: a cross-device `os.replace` raises `OSError(EXDEV)`.

    Asserted by capturing the staged path at the moment of the rename and proving it is under the
    destination's own root -- which is what makes the two ends of `os.replace` the same filesystem.
    """
    seen: list[tuple[Path, Path]] = []
    original = Path.replace

    def spy(self: Path, target: str | os.PathLike[str]) -> Path:
        seen.append((self, Path(target)))
        return original(self, target)

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(Path, "replace", spy)
        store.put(io.BytesIO(b"same filesystem, always"))

    (staged, final) = seen[-1]
    assert staged.parent == store.tmp_root
    assert staged.is_relative_to(store.root)
    assert final.is_relative_to(store.root)
    assert store.tmp_root.is_relative_to(store.root)


def test_the_temp_file_exists_and_is_fully_written_at_the_moment_of_the_rename(
    store: BlobStore,
) -> None:
    """Steps 1 and 2 happen, in that order, before step 3.

    Observing the filesystem inside the patched `os.replace` is the only place the ordering is
    visible: after `put` returns, an implementation that wrote the bytes *after* renaming an empty
    file would look identical.
    """
    payload = b"fully written before the rename" * 4_000
    observed: dict[str, object] = {}
    original = Path.replace

    def spy(self: Path, target: str | os.PathLike[str]) -> Path:
        observed["staged_exists"] = self.is_file()
        observed["staged_bytes"] = self.read_bytes()
        observed["final_absent"] = not Path(target).exists()
        return original(self, target)

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(Path, "replace", spy)
        digest = store.put(io.BytesIO(payload))

    assert observed["staged_exists"] is True
    assert observed["staged_bytes"] == payload
    assert observed["final_absent"] is True
    assert store.path(digest).read_bytes() == payload


def test_the_file_is_fsynced_before_the_rename_and_the_directory_after_it(
    store: BlobStore,
) -> None:
    """The four steps in order (07:906-909), as a sequence of observed events.

    `os.fsync` on the file descriptor is step 2 -- "else a rename can outlive the data" -- and the
    directory fsync is step 4 -- "else the rename can be lost on a crash (POSIX)". Recording both
    as one ordered list is what proves the second is *after* the rename rather than merely present.
    """
    events: list[str] = []
    real_fsync = os.fsync
    real_open = os.open
    real_replace = Path.replace
    directory_fds: set[int] = set()

    def spy_open(path: object, flags: int, *rest: object) -> int:
        fd = real_open(path, flags, *rest)  # type: ignore[arg-type]
        if Path(str(path)).is_dir():
            directory_fds.add(fd)
        return fd

    def spy_fsync(fd: int) -> None:
        events.append("fsync_dir" if fd in directory_fds else "fsync_file")
        real_fsync(fd)

    def spy_replace(self: Path, target: str | os.PathLike[str]) -> Path:
        events.append("replace")
        return real_replace(self, target)

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(os, "open", spy_open)
        mp.setattr(os, "fsync", spy_fsync)
        mp.setattr(Path, "replace", spy_replace)
        store.put(io.BytesIO(b"ordered"))

    assert events[:2] == ["fsync_file", "replace"], events
    if sys.platform != "win32":  # step 4 has no directory handle on Windows; see `_fsync_dir`
        assert events == ["fsync_file", "replace", "fsync_dir"], events


def test_the_staged_file_is_gone_after_a_successful_put(store: BlobStore) -> None:
    store.put(io.BytesIO(b"no residue"))
    assert list(store.tmp_root.iterdir()) == []


def test_putting_identical_bytes_twice_is_one_file_and_the_second_rename_is_a_no_op(
    store: BlobStore,
) -> None:
    """07:908: "overwrite is a no-op because the name IS the digest"."""
    payload = b"idempotent by construction"
    first = store.put(io.BytesIO(payload))
    inode_before = store.path(first).stat().st_size
    second = store.put(io.BytesIO(payload))

    assert first == second
    leaf = store.path(first).parent
    assert [p.name for p in leaf.iterdir()] == [first.hex()]
    assert store.path(first).read_bytes() == payload
    assert store.path(first).stat().st_size == inode_before
    assert list(store.tmp_root.iterdir()) == []


def test_two_concurrent_writers_in_one_process_never_share_a_staged_name(
    store: BlobStore,
) -> None:
    """`O_CREAT | O_EXCL` plus the counter is what replaces 07:906's banned `uuid4`."""
    staged: list[Path] = []
    original = Path.replace

    def spy(self: Path, target: str | os.PathLike[str]) -> Path:
        staged.append(self)
        return original(self, target)

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(Path, "replace", spy)
        for i in range(8):
            store.put(io.BytesIO(f"payload {i}".encode()))

    assert len({p.name for p in staged}) == len(staged)


def test_a_staged_name_already_taken_is_retried_rather_than_overwritten(
    store: BlobStore,
) -> None:
    """A recycled pid landing on a dead process's abandoned temp file must not corrupt it."""
    store.tmp_root.mkdir(parents=True, exist_ok=True)
    calls: list[str] = []
    real_open = os.open

    def spy_open(path: object, flags: int, *rest: object) -> int:
        if flags & os.O_EXCL:
            calls.append(str(path))
            if len(calls) == 1:
                raise FileExistsError(errno.EEXIST, "File exists", str(path))
        return real_open(path, flags, *rest)  # type: ignore[arg-type]

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(os, "open", spy_open)
        digest = store.put(io.BytesIO(b"retried"))

    assert len(calls) >= 2
    assert calls[0] != calls[1]
    assert store.path(digest).read_bytes() == b"retried"


def test_an_empty_stream_is_a_legal_blob(store: BlobStore) -> None:
    digest = store.put(io.BytesIO(b""))
    assert digest == sha256_of(b"")
    assert store.path(digest).read_bytes() == b""


def test_a_multi_chunk_stream_is_hashed_and_written_whole(store: BlobStore) -> None:
    payload = os.urandom(1) * (3 * (1 << 20) + 7)
    digest = store.put(io.BytesIO(payload))
    assert digest == sha256_of(payload)
    assert store.path(digest).stat().st_size == len(payload)


def test_a_blob_full_of_newlines_hashes_to_the_name_it_was_stored_under(
    store: BlobStore,
) -> None:
    """The one property `put` cannot check for itself: the file on disk IS the stream it was given.

    `put` hashes the bytes it is HANDED, streaming, and never re-reads what landed -- which is the
    right design (re-reading 256 MiB to confirm a write would double the cost of every ingest) and
    is precisely why nothing inside `BlobStore` could see this. On Windows, `os.open` without
    `O_BINARY` opens in the C runtime's text mode and rewrites every `0x0A` as `0x0D 0x0A`, so the
    file under `ab/cd/<sha256>` hashed to something else and step 3's safety argument at
    07-store-and-retrieval.md:914 -- "an overwrite is a no-op **because the name IS the digest**"
    -- was false for every blob containing a newline.

    The assertion is therefore deliberately NOT `digest == sha256_of(payload)`, which passed
    throughout: it re-hashes the file READ BACK OFF THE DISK and compares that to the name. The
    payload is chosen so text-mode translation is unmissable: a bare `0x0A`, one already preceded
    by `0x0D` (which text mode would turn into `0x0D 0x0D 0x0A`), a trailing one, and a `0x1A`,
    which the same text mode historically treated as end-of-file on the way back in.
    """
    payload = b"line\n\r\nmid\n\x1a\ntail\n"
    digest = store.put(io.BytesIO(payload))
    on_disk = store.path(digest).read_bytes()
    assert on_disk == payload, "the CAS stored translated bytes"
    assert hashlib.sha256(on_disk).hexdigest() == digest.hex(), (
        "the file under the digest name does not hash to that name"
    )
    with store.open(digest) as fh:
        assert fh.read() == payload


# ---------------------------------------------------------------------------
# 4. Crash recovery: the startup sweep of `cas/tmp/`.
# ---------------------------------------------------------------------------


def test_a_sigkill_equivalent_leaves_the_cas_clean_and_loses_nothing_committed(
    store: BlobStore,
) -> None:
    """A SIGKILL between steps 1 and 3 (07:928-930), as an abandoned temp file.

    The kill is modelled by letting `put` stage its bytes and then raising instead of renaming,
    which is exactly the state a killed process leaves: a full temp file, no digest-named file, no
    row. What must survive is everything already committed; what must go is the staged file.
    """
    committed = store.put(io.BytesIO(b"committed before the crash"))

    class Kill(BaseException):
        """Not an `Exception`, so an `except Exception` anywhere would not catch it either."""

    def die(self: Path, target: str | os.PathLike[str]) -> Path:  # noqa: ARG001 -- a spy
        raise Kill

    abandoned: list[Path] = []
    real_open = os.open

    def spy_open(path: object, flags: int, *rest: object) -> int:
        if flags & os.O_EXCL:
            abandoned.append(Path(str(path)))
        return real_open(path, flags, *rest)  # type: ignore[arg-type]

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(os, "open", spy_open)
        # Neutralise the module's own belt-and-braces unlink, so what the sweep faces is what a
        # SIGKILLed process would actually have left: the file, untouched.
        mp.setattr(Path, "unlink", _keep_the_file)
        mp.setattr(Path, "replace", die)
        with pytest.raises(Kill):
            store.put(io.BytesIO(b"lost in the crash"))

    staged = abandoned[-1]
    assert staged.is_file(), "the SIGKILL-equivalent must leave a staged file behind"
    assert staged.read_bytes() == b"lost in the crash"
    assert not store.has(sha256_of(b"lost in the crash"))

    assert store.sweep_tmp() == 1
    assert list(store.tmp_root.iterdir()) == []
    assert store.path(committed).read_bytes() == b"committed before the crash"
    assert store.verify(committed) is True


def test_the_startup_sweep_of_tmp_is_a_no_op_on_a_clean_store(store: BlobStore) -> None:
    assert store.sweep_tmp() == 0
    store.put(io.BytesIO(b"clean"))
    assert store.sweep_tmp() == 0


def test_the_startup_sweep_never_touches_a_committed_blob(store: BlobStore) -> None:
    digest = store.put(io.BytesIO(b"committed"))
    (store.tmp_root / "abandoned-1").write_bytes(b"junk")
    (store.tmp_root / "abandoned-2").write_bytes(b"junk")
    assert store.sweep_tmp() == 2
    assert store.has(digest)


def test_the_write_paths_own_unlink_is_belt_to_the_startup_sweeps_braces(
    store: BlobStore,
) -> None:
    """A failure the process survives cleans up after itself. The sweep is for the others."""

    def boom(self: Path, target: str | os.PathLike[str]) -> Path:  # noqa: ARG001 -- a spy
        raise OSError(errno.EIO, "I/O error")

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(Path, "replace", boom)
        with pytest.raises(OSError, match="I/O error"):
            store.put(io.BytesIO(b"failed but alive"))

    assert list(store.tmp_root.iterdir()) == []


# ---------------------------------------------------------------------------
# 5. Mark-and-sweep, and the file-before-row ordering.
# ---------------------------------------------------------------------------


def test_the_sweep_deletes_exactly_the_blobs_live_does_not_name(store: BlobStore) -> None:
    digests = [store.put(io.BytesIO(f"blob {i}".encode())) for i in range(3)]
    keep = digests[1]

    report = store.sweep(lambda: [keep])

    assert report.scanned == 3
    assert report.files_deleted == 2
    assert store.has(keep)
    assert not store.has(digests[0])
    assert not store.has(digests[2])


def test_the_sweep_deletes_the_file_before_the_row(store: BlobStore) -> None:
    """07:930-932, and the reason `forget` is a parameter rather than the caller's next statement.

    The order is observed, not inferred: `forget` asserts that the file is *already* gone at the
    moment it runs. The inverse order leaves a dangling file -- a leak nothing will ever collect --
    where this order leaves at worst a dangling row, which `ow store fsck --cas` repairs.
    """
    store.put(io.BytesIO(b"doomed"))
    kept = store.put(io.BytesIO(b"kept"))
    order: list[str] = []

    def forget(digest: bytes) -> None:
        order.append("row")
        assert not store.path(digest).exists(), "the row was deleted before the file"

    real_unlink = Path.unlink

    def spy_unlink(self: Path, missing_ok: bool = False) -> None:
        order.append("file")
        real_unlink(self, missing_ok=missing_ok)

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(Path, "unlink", spy_unlink)
        report = store.sweep(lambda: [kept], forget=forget)

    assert order == ["file", "row"]
    assert report.rows_forgotten == 1
    assert report.files_deleted == 1


def test_the_sweep_calls_live_exactly_once(store: BlobStore) -> None:
    """The mark is one point in time, not a per-candidate query (07:97's shape)."""
    for i in range(5):
        store.put(io.BytesIO(f"b{i}".encode()))
    calls = 0

    def live() -> list[bytes]:
        nonlocal calls
        calls += 1
        return []

    store.sweep(live)
    assert calls == 1


def test_the_sweep_forgets_a_row_whose_file_was_already_gone(store: BlobStore) -> None:
    """The dangling row is the recoverable case, so the sweep repairs it rather than raising."""
    digest = store.put(io.BytesIO(b"vanished"))
    forgotten: list[bytes] = []
    real_unlink = Path.unlink

    def vanish(self: Path, missing_ok: bool = False) -> None:
        real_unlink(self, missing_ok=missing_ok)
        raise FileNotFoundError(errno.ENOENT, "No such file", str(self))

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(Path, "unlink", vanish)
        report = store.sweep(lambda: [], forget=forgotten.append)

    assert forgotten == [digest]
    assert report.rows_forgotten == 1
    assert report.files_deleted == 0


def test_the_sweep_reports_the_bytes_it_reclaimed(store: BlobStore) -> None:
    store.put(io.BytesIO(b"a" * 100))
    store.put(io.BytesIO(b"b" * 250))
    report = store.sweep(lambda: [])
    assert report.bytes_reclaimed == 350


def test_the_sweep_ignores_the_headroom_file_and_the_tmp_directory(store: BlobStore) -> None:
    """A sweep that deleted what it could not name would delete a future schema's files."""
    kept = store.put(io.BytesIO(b"kept"))
    store.headroom()
    store._latch_no_space(Headroom(0, 1, 0, latched=True))  # writes the headroom file
    (store.tmp_root / "staged").write_bytes(b"junk")
    (store.root / "README.txt").write_bytes(b"not a blob")
    (store.root / "zz").mkdir()
    (store.root / "zz" / "zz").mkdir(parents=True)
    (store.root / "zz" / "zz" / ("0" * 64)).write_bytes(b"outside the hex fanout")

    report = store.sweep(lambda: [kept])

    assert report.scanned == 1
    assert report.files_deleted == 0
    assert store.headroom_path.is_file()
    assert (store.tmp_root / "staged").is_file()
    assert (store.root / "README.txt").is_file()
    assert (store.root / "zz" / "zz" / ("0" * 64)).is_file()


def test_the_sweep_accepts_a_live_set_that_names_a_blob_the_store_does_not_hold(
    store: BlobStore,
) -> None:
    kept = store.put(io.BytesIO(b"present"))
    report = store.sweep(lambda: [kept, sha256_of(b"never stored")])
    assert report.files_deleted == 0
    assert store.has(kept)


# ---------------------------------------------------------------------------
# 6. The read path and its confinement.
# ---------------------------------------------------------------------------


def test_open_returns_the_bytes_that_were_put(store: BlobStore) -> None:
    digest = store.put(io.BytesIO(b"read me back"))
    with store.open(digest) as fh:
        assert fh.read() == b"read me back"
    with store.open_ref(format_ref(digest)) as fh:
        assert fh.read() == b"read me back"


def test_open_refuses_a_traversal_reference_rather_than_reading_it(store: BlobStore) -> None:
    with pytest.raises(UsageError):
        store.open_ref("cas://../../etc/passwd")
    with pytest.raises(UsageError):
        store.open_ref("cas://%2e%2e/%2e%2e/etc/passwd")


def test_open_refuses_a_digest_that_is_not_a_digest(store: BlobStore) -> None:
    with pytest.raises(UsageError):
        store.open("../../etc/passwd")
    with pytest.raises(UsageError):
        store.open("..")


def test_open_refuses_a_blob_that_is_a_symlink_out_of_the_cas_root(
    store: BlobStore, tmp_path: Path
) -> None:
    """The grammar makes the NAME safe; resolution is what catches a planted link.

    14-security.md:298-309: resolve, then contain, then use the resolved value. The skip is
    conditional on the *attempt* rather than on `sys.platform`, because a Windows developer with
    the create-symlink privilege can run this and a `skipif` would deny them the coverage.
    """
    secret = tmp_path / "shadow"
    secret.write_bytes(b"root:!:19000:0:99999:7:::")
    digest = sha256_of(b"whatever")
    planted = store.path(digest)
    planted.parent.mkdir(parents=True, exist_ok=True)
    try:
        planted.symlink_to(secret)
    except (OSError, NotImplementedError) as exc:  # pragma: no cover - unprivileged Windows
        pytest.skip(f"this filesystem will not plant a symlink: {exc}")

    with pytest.raises(UsageError, match="outside the CAS root"):
        store.open(digest)


def test_open_reports_a_dangling_row_as_a_store_error_naming_the_fix(store: BlobStore) -> None:
    missing = sha256_of(b"never stored")
    with pytest.raises(StoreError, match="dangling") as caught:
        store.open(missing)
    assert caught.value.fix == "ow store fsck --cas"


def test_verify_re_hashes_and_catches_a_content_mismatch(store: BlobStore) -> None:
    """07:920-923: a hash collision is not handled, a content mismatch is."""
    digest = store.put(io.BytesIO(b"authentic"))
    assert store.verify(digest) is True
    store.path(digest).write_bytes(b"tampered")
    assert store.verify(digest) is False


def test_the_root_must_already_exist(tmp_path: Path) -> None:
    """14-security.md:278-280: a resolver that accepts a missing base is a file oracle."""
    with pytest.raises(StoreError, match="does not exist"):
        BlobStore(tmp_path / "absent")


# ---------------------------------------------------------------------------
# 7. `MAX_ASSET_BYTES` and ENOSPC.
# ---------------------------------------------------------------------------


def test_max_asset_bytes_is_the_constant_the_plan_sets(store: BlobStore) -> None:
    """07:934 and limits.py:313. One home, reused -- never a second copy here."""
    assert MAX_ASSET_BYTES == 268_435_456
    assert store.max_bytes == MAX_ASSET_BYTES


def test_a_tenant_may_clamp_the_ceiling_down_and_never_up(tmp_path: Path) -> None:
    """INV-22 via `limits.effective`: `min(tenant_cap, declared, HOST_MAX)`."""
    root = tmp_path / "cas"
    root.mkdir()
    assert BlobStore(root, max_bytes=1024).max_bytes == 1024
    assert BlobStore(root, max_bytes=MAX_ASSET_BYTES * 4).max_bytes == MAX_ASSET_BYTES


def test_over_size_input_is_refused_at_the_ceiling_naming_the_knob(tmp_path: Path) -> None:
    root = tmp_path / "cas"
    root.mkdir()
    store = BlobStore(root, max_bytes=64)

    assert store.put(io.BytesIO(b"x" * 64)) == sha256_of(b"x" * 64)
    with pytest.raises(ResourceLimit, match="MAX_ASSET_BYTES") as caught:
        store.put(io.BytesIO(b"x" * 65))
    assert caught.value.limit == "MAX_ASSET_BYTES"
    assert caught.value.code() == "OW_RESOURCE_LIMIT"


def test_over_size_input_is_refused_without_buffering_the_whole_stream(tmp_path: Path) -> None:
    """`take(N+1)`-then-check: the refusal is a refusal, not a measurement after the fact.

    A stream that would be 4 GiB if drained is refused after reading at most `max_bytes + 1` bytes,
    and the reader counts what it was asked for -- so the assertion is on the *number of bytes
    handed over*, not on process memory, which no test can observe portably.
    """

    class Endless(io.RawIOBase):
        served = 0

        def readable(self) -> bool:
            return True

        def readinto(self, buffer: memoryview) -> int:  # type: ignore[override]
            Endless.served += len(buffer)
            buffer[:] = b"\x00" * len(buffer)
            return len(buffer)

    limit = 4 * (1 << 20) + 3
    store = BlobStore(tmp_path, max_bytes=limit)
    with pytest.raises(ResourceLimit, match="MAX_ASSET_BYTES"):
        store.put(io.BufferedReader(Endless(), buffer_size=1 << 20))  # type: ignore[arg-type]

    assert Endless.served <= limit + (1 << 20), Endless.served
    assert list((tmp_path / "tmp").iterdir()) == []


def test_the_over_size_refusal_leaves_no_staged_file_behind(tmp_path: Path) -> None:
    root = tmp_path / "cas"
    root.mkdir()
    store = BlobStore(root, max_bytes=8)
    with pytest.raises(ResourceLimit):
        store.put(io.BytesIO(b"far too many bytes"))
    assert list(store.tmp_root.iterdir()) == []
    assert store.sweep(lambda: []).scanned == 0


def test_enospc_in_step_one_becomes_ow_resource_limit_naming_the_knob(store: BlobStore) -> None:
    """07:928-930: "ENOSPC in step 1 aborts the unit with `OW_RESOURCE_LIMIT`"."""
    real_write = os.write

    def full(fd: int, data: bytes) -> int:  # noqa: ARG001 -- a spy over os.write
        raise OSError(errno.ENOSPC, "No space left on device")

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(os, "write", full)
        with pytest.raises(ResourceLimit, match="out of space") as caught:
            store.put(io.BytesIO(b"no room"))

    assert caught.value.limit == "cache.min_free_bytes"
    assert caught.value.code() == "OW_RESOURCE_LIMIT"
    assert os.write is real_write


def test_a_disk_quota_breach_is_also_ow_resource_limit(store: BlobStore) -> None:
    def over_quota(fd: int, data: bytes) -> int:  # noqa: ARG001 -- a spy over os.write
        raise OSError(errno.EDQUOT, "Disk quota exceeded")

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(os, "write", over_quota)
        with pytest.raises(ResourceLimit):
            store.put(io.BytesIO(b"over quota"))


def test_a_permission_error_is_not_dressed_up_as_a_resource_limit(store: BlobStore) -> None:
    """A `ResourceLimit` names the knob that clears it, so it must not name a wrong one."""

    def denied(fd: int, data: bytes) -> int:  # noqa: ARG001 -- a spy over os.write
        raise PermissionError(errno.EACCES, "Permission denied")

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(os, "write", denied)
        with pytest.raises(PermissionError):
            store.put(io.BytesIO(b"denied"))


# ---------------------------------------------------------------------------
# 8. The headroom file and the write refusal. 08-runtime.md section 4.7(a).
# ---------------------------------------------------------------------------


def test_min_free_bytes_is_configs_five_gibibytes_and_is_not_copied_here(
    store: BlobStore,
) -> None:
    """08:1490's `5368709120` has one home: `config.KEYS` (config.py:835)."""
    assert KEYS["cache.min_free_bytes"].default == 5_368_709_120
    assert store.headroom().min_free_bytes == 5_368_709_120


def test_headroom_measures_free_space_under_the_cas_root(store: BlobStore) -> None:
    state = store.headroom()
    assert state.free_bytes > 0
    assert state.latched is False
    assert state.refuses is False


def test_a_write_is_refused_when_free_space_is_below_min_free_bytes(tmp_path: Path) -> None:
    """The refusal names the knob, which is the one thing 08:1490 requires of it."""
    root = tmp_path / "cas"
    root.mkdir()
    store = BlobStore(root, min_free_bytes=1 << 62)

    with pytest.raises(ResourceLimit, match="min_free_bytes") as caught:
        store.put(io.BytesIO(b"no headroom"))

    assert caught.value.limit == "cache.min_free_bytes"
    assert NO_SPACE_DEGRADATION_KIND in str(caught.value)
    assert caught.value.EXIT == 1  # "usage or configuration error", 18-api-sketch.md section 0.3


def test_the_first_refusal_latches_into_the_headroom_file(tmp_path: Path) -> None:
    """08:1493-1496: the latch is what makes every later write a skip and not an event."""
    root = tmp_path / "cas"
    root.mkdir()
    store = BlobStore(root, min_free_bytes=1 << 62)
    with pytest.raises(ResourceLimit):
        store.put(io.BytesIO(b"first"))

    assert (root / HEADROOM_FILENAME).is_file()
    recorded = json.loads((root / HEADROOM_FILENAME).read_text("utf-8"))
    assert recorded["latched"] is True
    assert recorded["knob"] == "cache.min_free_bytes"
    assert recorded["degradation"] == NO_SPACE_DEGRADATION_KIND


def test_the_latch_is_shared_with_a_second_process_through_the_file(tmp_path: Path) -> None:
    """Which is the whole reason the latch is a file and not an attribute.

    A second `BlobStore` over the same root -- standing in for the second worker of a multi-process
    run -- must refuse without measuring, or a full disk gets hammered once per worker.
    """
    root = tmp_path / "cas"
    root.mkdir()
    first = BlobStore(root, min_free_bytes=1 << 62)
    with pytest.raises(ResourceLimit):
        first.put(io.BytesIO(b"first"))

    def unmeasurable(_path: object) -> object:
        raise AssertionError("a latched store must not re-measure free space")

    second = BlobStore(root)  # the generous default ceiling, so only the latch can refuse it
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr("omniweave_core.blobs.shutil.disk_usage", unmeasurable)
        assert second.headroom().refuses is True
        with pytest.raises(ResourceLimit):
            second.put(io.BytesIO(b"second"))


def test_a_latched_store_does_not_re_measure_free_space(tmp_path: Path) -> None:
    root = tmp_path / "cas"
    root.mkdir()
    store = BlobStore(root, min_free_bytes=1 << 62)
    with pytest.raises(ResourceLimit):
        store.put(io.BytesIO(b"first"))

    calls = 0
    real = os.stat

    def counting_disk_usage(path: object) -> object:
        nonlocal calls
        calls += 1
        return real(path)

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr("omniweave_core.blobs.shutil.disk_usage", counting_disk_usage)
        for _ in range(5):
            with pytest.raises(ResourceLimit):
                store.put(io.BytesIO(b"again"))

    assert calls == 0


def test_clearing_the_latch_lets_writes_resume(tmp_path: Path) -> None:
    """A new run's business: 08:1494 latches "for the rest of the run", not for ever."""
    root = tmp_path / "cas"
    root.mkdir()
    store = BlobStore(root, min_free_bytes=1 << 62)
    with pytest.raises(ResourceLimit):
        store.put(io.BytesIO(b"refused"))

    store.clear_latch()
    assert not store.headroom_path.exists()

    generous = BlobStore(root)
    assert generous.put(io.BytesIO(b"allowed")) == sha256_of(b"allowed")


def test_a_corrupt_headroom_file_costs_one_syscall_and_never_an_exception(
    store: BlobStore,
) -> None:
    """It is a cache of a `statvfs`; raising here would fail every write in the run."""
    store.headroom_path.write_text("{ this is not json", "utf-8")
    assert store.headroom().refuses is False
    assert store.put(io.BytesIO(b"unbothered")) == sha256_of(b"unbothered")

    store.headroom_path.write_text(json.dumps({"schema": 999, "latched": True}), "utf-8")
    assert store.headroom().refuses is False

    store.headroom_path.write_text(json.dumps({"schema": 1}), "utf-8")
    assert store.headroom().refuses is False


def test_headroom_can_be_read_without_measuring(store: BlobStore) -> None:
    """`ow doctor` reports the latch; it does not need to re-measure to do it."""

    def unmeasurable(_path: object) -> object:
        raise AssertionError("measure=False must not call disk_usage")

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr("omniweave_core.blobs.shutil.disk_usage", unmeasurable)
        state = store.headroom(measure=False)
    assert state.latched is False
    assert state.free_bytes == -1


def test_refuses_is_true_on_a_short_measurement_and_on_a_latch() -> None:
    assert Headroom(0, 10, 0, latched=False).refuses is True
    assert Headroom(10, 10, 0, latched=False).refuses is False
    assert Headroom(1 << 60, 10, 0, latched=True).refuses is True


def test_the_headroom_file_survives_a_full_disk_by_giving_up_quietly(tmp_path: Path) -> None:
    """The condition being recorded is "the disk is full", so its own write may fail."""
    root = tmp_path / "cas"
    root.mkdir()
    store = BlobStore(root, min_free_bytes=1 << 62)

    real_write_text = Path.write_text

    def full(self: Path, *args: object, **kwargs: object) -> int:
        if self.parent == store.tmp_root:
            raise OSError(errno.ENOSPC, "No space left on device")
        return real_write_text(self, *args, **kwargs)  # type: ignore[arg-type]

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(Path, "write_text", full)
        with pytest.raises(ResourceLimit):
            store.put(io.BytesIO(b"nope"))

    assert not store.headroom_path.exists()
    # The in-process flag is the fallback, so the same store still refuses without measuring.
    assert store.headroom().refuses is True


# ---------------------------------------------------------------------------
# 9. The eager-module properties: INV-17 and G17.
# ---------------------------------------------------------------------------


def _modules_loaded_by(statement: str) -> set[str]:
    """`sys.modules` after `statement` runs in a fresh interpreter.

    The `subprocess` import at the top of this file takes `# noqa: TID251` for the reason
    tests/unit/test_core_eager_surface.py:15 gives: a fresh interpreter is the only witness for
    G17 and INV-17. Once *this* test process has imported `omniweave_core.model` for its own
    reasons -- and `test_the_two_retention_axes_are_different_closed_domains` above does exactly
    that -- `sys.modules` can no longer say whether importing `blobs` was what pulled it in. The
    ban's premise (INV-3: core must not spawn) is not being dodged: nothing under `src/` spawns,
    and this is a test asserting a property of `src/`.
    """
    code = f"{statement}\nimport json as _j, sys as _s\nprint(_j.dumps(sorted(_s.modules)))"
    proc = subprocess.run(  # noqa: S603
        [sys.executable, "-c", code], capture_output=True, text=True, check=True
    )
    return set(json.loads(proc.stdout.strip().splitlines()[-1]))


def test_importing_blobs_loads_no_sqlite3_and_none_of_the_nine_lazy_names() -> None:
    """INV-17 and G17 over an eager module. 11-repo-layout.md:198 puts `blobs.py` above `store/`.

    This is the property that makes the `live` callable necessary rather than stylistic: if `blobs`
    could import `store`, the refcount query could live here and the seam would not exist.
    """
    loaded = _modules_loaded_by("import omniweave_core.blobs")

    assert "sqlite3" not in loaded
    eager = sorted(name for name in LAZY if f"omniweave_core.{name}" in loaded)
    assert eager == [], f"blobs.py eagerly imported {eager}"


def test_blobs_source_imports_no_sqlite3_no_lazy_name_and_no_banned_ambient_input() -> None:
    """The source half of the same property, so a *lazily* imported name is caught too.

    Walked with `ast` rather than grepped, for the reason 02-architecture.md:395-398 gives the layer
    gate: a substring match cannot tell an import from the prose that cites the rule, and this
    module's own docstring names `sqlite3` twice while importing it nowhere.
    """
    source = (
        Path(__file__).resolve().parents[2] / "src" / "omniweave_core" / "blobs.py"
    ).read_text("utf-8")
    tree = ast.parse(source)

    roots: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            roots.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            roots.add(node.module.split(".")[0])
            if node.module.startswith("omniweave_core."):
                roots.add(node.module)

    assert "sqlite3" not in roots, "INV-17: sqlite3 is legal only under store/"
    for name in LAZY:
        assert f"omniweave_core.{name}" not in roots, f"G17: blobs.py imports {name}"
    # The five ambient inputs 02-architecture.md:392 bans in library code, `uuid` included --
    # which is why `put`'s staged name is `<pid>-<counter>` and not 07:906's `<uuid4>`.
    assert roots.isdisjoint({"uuid", "random", "secrets", "asyncio", "opentelemetry"})

    banned_calls = {"uuid4", "uuid1", "time", "time_ns", "perf_counter", "perf_counter_ns"}
    called: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            func = node.func
            if isinstance(func, ast.Attribute):
                called.add(func.attr)
            elif isinstance(func, ast.Name):
                called.add(func.id)
    assert called.isdisjoint(banned_calls), sorted(called & banned_calls)
