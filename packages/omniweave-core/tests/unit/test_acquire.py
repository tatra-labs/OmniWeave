"""`acquire.fs.local`: the normalisation surface, the capture order, and the coverage arithmetic.

W3.8's estimation basis (16-roadmap.md:527) names one correctness surface and this file is built
around it: *"the realpath / normcase / `\\\\?\\`-stripping normalisation is the whole correctness
surface and the reason `canonical_uri()` is one function"*. So the first group asserts that six
spellings of one tree reach one `unit_uri` **and that two different trees do not** -- the second
direction being the half that gets forgotten -- and then asserts structurally that this module
contains no second normaliser to disagree with the first.

The other two groups are the two orderings that fail silently:

* the stat triple is captured BEFORE the content read (02-architecture.md:472, 05:344), so
  `test_the_stat_triple_is_the_one_captured_before_the_content_read` mutates the file *between*
  the two operations through the injected reader and asserts the triple describes the file as it
  was. Asserting the values alone would pass on a stat-after-read implementation.
* the roster upsert refreshes `last_seen_gen` and `cursor` and nothing else (05:395-398), so a
  re-scan may not overwrite the stored triple -- because `stat_fresh` compares the stored triple
  against a fresh `stat`, and an enumerator that re-stamped it would make every unit fresh
  forever.

And the coverage arithmetic: `discovered == indexed + skipped`, every skip carrying a reason, and
`complete = 0` for a truncated scan.

Every constant is pinned against `_plan/` where the design tree is present and against a literal
otherwise. Nothing here imports a threshold from its subject and compares it to itself.

Specified in 05-ingest-and-routing.md sections 1.1-1.5, 02-architecture.md:472,
04-driver-system.md sections 1.4-1.5, 07-store-and-retrieval.md section 3.8 and 16-roadmap.md:527.
"""

from __future__ import annotations

import ast
import hashlib
import importlib.util
import inspect
import io
import json
import os
import re
import sqlite3  # noqa: TID251 -- see below.
import subprocess  # noqa: TID251 -- `mklink /J` is the only way to make a junction; see below.
import sys
import textwrap
from collections.abc import Callable, Iterator, Sequence
from dataclasses import dataclass, field
from pathlib import Path

import pytest
from omniweave_core import acquire
from omniweave_core.acquire import (
    CURSOR_SEP,
    CandidateRecord,
    FsLocal,
    IngestGuards,
    RosterRow,
    Scope,
    ScopeTally,
    StatTriple,
    Tally,
    TrustClass,
    fetch_local,
    in_scope,
    iter_candidates,
    locator_for,
    roster_row_of,
    scan,
    scope_id_for,
    stat_fresh,
    walk_order,
    write_roster,
)
from omniweave_core.errors import PolicyRefusal, StoreError
from omniweave_core.store import migrate
from omniweave_core.store import sqlite as ow
from omniweave_ports.ports import AcquireV1
from omniweave_ports.types import (
    DriverError,
    FailureClass,
    ProbeEnv,
    ProbeStatus,
    UnitRef,
)

# `import sqlite3` is banned outside `omniweave_core/store/` by ruff's TID251 (INV-17), and the
# ban is about who may OPEN a connection: 07-store-and-retrieval.md:2721, "`sqlite3.connect`
# appears in exactly one module (ST1)". This file opens none -- every connection comes from
# `ow.connect()` on a `StoreThread` -- and the import is here only to ANNOTATE the closures
# `_unit_row` and the round-trip test hand to `ow.Unit`, whose `run` parameter is typed
# `sqlite3.Connection` by `store/sqlite.py`. `test_store_queue.py:34` takes the same reading for
# the same reason.

MODULE = Path(inspect.getsourcefile(acquire) or "")
WINDOWS = sys.platform == "win32"

# `subprocess` is banned under `packages/*/src/**` and this is a test, not library code -- the
# same reading `test_identity.py:17` and `tools/gate_semgrep.py:26-37` take. It is here for one
# reason: a Windows DIRECTORY JUNCTION cannot be created from Python without the privilege
# `os.symlink` needs, and `mklink /J` can. A junction is the reparse point a Windows user
# actually has, so skipping it would leave the platform where the normalisation bites untested.

# The columns a `discovered` unit row carries, spelled out here rather than imported, so that a
# column dropped from `UNIT_COLUMNS` fails a test instead of silently narrowing every write.
DISCOVERED_COLUMNS = (
    "unit_uri",
    "connector",
    "cursor",
    "state",
    "size",
    "mtime_ns",
    "indexed_at_ns",
    "derived",
    "trust_class",
    "last_seen_gen",
    "scope_rule",
)


# --------------------------------------------------------------------------------------------
# Fixtures and doubles
# --------------------------------------------------------------------------------------------


@pytest.fixture
def tree(tmp_path: Path) -> Path:
    """A small corpus with one of each thing the guards have to decide about.

    ```
    a/                    a directory whose NAME is a prefix of a sibling FILE's name
      b.txt
    a.txt                 the `walk_order` witness: "a.txt" < "a/b.txt" as strings
    docs/
      reports/
        deep.txt
      q3.pdf
    node_modules/         the shipped exclude default, AT THE ROOT
      react/index.js
    nodemodules/          NOT excluded: the pattern names `node_modules`, not a prefix of it
      keep.txt
    .hidden/              a dotted directory: `[ingest] hidden = false`
      secret.txt
    readme.md
    ```
    """
    root = tmp_path / "corpus"
    for relative, body in (
        ("a/b.txt", "ab"),
        ("a.txt", "a"),
        ("docs/q3.pdf", "%PDF-1.4"),
        ("docs/reports/deep.txt", "deep"),
        ("node_modules/react/index.js", "react"),
        ("nodemodules/keep.txt", "keep"),
        (".hidden/secret.txt", "secret"),
        ("readme.md", "readme"),
    ):
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(body, encoding="utf-8")
    return root


@pytest.fixture
def symlinks(tmp_path: Path) -> None:
    """Skip unless this machine can create a symlink, PROBED rather than assumed.

    A platform check would be the wrong test: `os.symlink` on Windows needs either Developer
    Mode or `SeCreateSymbolicLinkPrivilege`, and it works on plenty of Windows machines --
    including one running this suite. Skipping the whole platform would silently drop the
    `realpath` cases on the operating system whose path spellings are the reason
    `canonical_uri()` exists. So the capability is measured here and the junction test below
    covers the case where the answer is no.
    """
    probe = tmp_path / "probe"
    probe.mkdir()
    (probe / "target").write_text("x", encoding="utf-8")
    try:
        (probe / "link").symlink_to(probe / "target")
    except OSError as error:  # pragma: no cover - depends on the machine's privileges
        pytest.skip(f"this machine cannot create a symlink: {error}")


@pytest.fixture
def store(tmp_path: Path) -> Iterator[ow.StoreThread]:
    """A real migrated store on a real `StoreThread`.

    `now_ns` is pinned so two migrations of two fixtures write identical ledger rows, the same
    injection `store/crashmatrix.py:678` documents.
    """
    path = tmp_path / "index.owstore"
    connection = ow.connect(path)
    try:
        migrate.apply_pending(connection, now_ns=1_700_000_000_000_000_000)
    finally:
        connection.close()
    with ow.StoreThread(lambda: ow.connect(path)) as thread:
        yield thread


@dataclass
class RecordingThread:
    """A `StoreThread` stand-in that records the TRANSACTIONS it was asked to run.

    `write_roster`'s contract is about transaction boundaries -- 512 rows each, and the coverage
    row inside the last one -- and a real store would let those boundaries pass unobserved. This
    double records one entry per submitted `Unit`, so a test can assert the batching and the
    placement rather than only the final row count.
    """

    transactions: list[tuple[str, ...]] = field(default_factory=list)
    batch_sizes: list[int] = field(default_factory=list)
    wait_ms: list[int] = field(default_factory=list)

    def run(self, unit: object, *, timeout_s: float | None = None) -> object:
        del timeout_s
        statements: list[str] = []
        sizes: list[int] = []

        class Connection:
            def execute(self, sql: str, _parameters: object = (), /) -> object:
                statements.append(sql)
                return _Empty()

            def executemany(self, sql: str, parameters: Sequence[object], /) -> object:
                statements.append(sql)
                sizes.append(len(parameters))
                return _Empty()

        result = unit.run(Connection())  # type: ignore[attr-defined]
        self.transactions.append(tuple(statements))
        self.batch_sizes.extend(sizes)
        self.wait_ms.append(unit.wait_ms)  # type: ignore[attr-defined]
        return result


class _Empty:
    """A cursor whose `fetchall()` is empty -- enough for `refuse_unmigrated`'s one query."""

    def fetchall(self) -> list[tuple[str, ...]]:
        return []


def _walk(root: Path, **kwargs: object) -> tuple[CandidateRecord, ...]:
    """Every candidate one full enumeration of `root` emits, with the default guards."""
    locator = locator_for(root, cursor=kwargs.pop("cursor", None))  # type: ignore[arg-type]
    scope = Scope(roots=(locator.target,), **kwargs)  # type: ignore[arg-type]
    return tuple(iter_candidates(locator, scope, IngestGuards(), tally=Tally()))


def _uris(root: Path, **kwargs: object) -> frozenset[str]:
    """The `unit_uri` set one enumeration of `root` produces, minted the host's way."""
    locator = locator_for(root)
    scope = Scope(roots=(locator.target,), **kwargs)  # type: ignore[arg-type]
    tally = Tally()
    rows = scan(locator, scope, IngestGuards(), indexed_at_ns=1, last_seen_gen=1, tally=tally)
    return frozenset(row.unit_uri for row in rows)


# --------------------------------------------------------------------------------------------
# 1. The normalisation surface -- one uri for one file, and two for two
# --------------------------------------------------------------------------------------------


def test_six_spellings_of_one_root_reach_one_set_of_unit_uris(tree: Path) -> None:
    """05:239's `file`/`dir` row: *"two spellings of one path must not make two units"*.

    Six spellings of the same directory, every one of which a user or a tool really produces: as
    given, with a trailing separator, with a doubled separator, upper-cased, with backslashes, and
    with the Windows extended-length `\\\\?\\` prefix. Each is walked from scratch and the minted
    `unit_uri` sets are compared.

    The last three are Windows-only for two different reasons. Backslashes and `\\\\?\\` are not
    separators on POSIX, so those spellings would name a single file with an odd name. And an
    UPPER-CASED path is a *different path* on a case-sensitive filesystem -- it names a directory
    that does not exist, `_uris` returns the empty set, and the assertion fails for a reason that
    has nothing to do with normalisation.

    **The case fold needs its own assertion and cannot ride on the upper-cased spelling.**
    `Path.resolve()` on Windows answers through `GetFinalPathNameByHandle`, which returns the
    on-disk casing of an existing path -- so `C:\\...\\CORPUS` is already folded back to
    `C:\\...\\corpus` before `os.path.normcase` is reached, and all six sets agree even with
    `normcase` deleted from `identity._canonical_path`. What `normcase` actually contributes is
    the lower-casing itself (the drive letter above all, which `resolve()` leaves as given), so
    that is pinned as a value: on Windows a minted `unit_uri` contains no upper-case character.
    """
    spellings = [
        str(tree),
        str(tree) + os.sep,
        str(tree) + os.sep + os.sep,
        str(tree).upper() if WINDOWS else str(tree),
        str(tree).replace("/", "\\") if WINDOWS else str(tree),
        (f"\\\\?\\{tree}" if WINDOWS else str(tree)),
    ]
    expected = _uris(tree)
    assert expected, "the fixture tree produced no units at all"
    for spelling in spellings:
        assert _uris(Path(spelling)) == expected, spelling
    if WINDOWS:
        assert expected == frozenset(uri.lower() for uri in expected)


def test_a_mixed_separator_root_and_a_forward_slash_root_are_one_scope(tree: Path) -> None:
    """`normcase` folds the separator, so `docs\\reports` and `docs/reports` are one prefix.

    The scope_id is what absence gate 4 selects documents by (`doc.uri GLOB scope_id || '*'`), so
    two spellings producing two prefixes would give one corpus two coverage rows and let a clean
    scan look incomplete.
    """
    forward = scope_id_for(locator_for(tree))
    mixed = scope_id_for(locator_for(Path(str(tree).replace("/", os.sep))))
    assert forward == mixed
    assert forward.endswith("/")


def test_a_sibling_root_sharing_a_name_prefix_is_a_different_scope(tmp_path: Path) -> None:
    """The direction people forget: `docs` and `docs2` must NOT be one scope.

    `ingest_scope.scope_id` is a URI *prefix* and the containment test is
    `doc.uri GLOB scope_id || '*'` (07 section 3.8), so a `scope_id` without its trailing
    separator would make every document under `docs2/` a member of `docs`'s coverage row -- and
    gate 4 would then read a coverage claim about documents that scan never saw.
    """
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs2").mkdir()
    (tmp_path / "docs" / "one.txt").write_text("1", encoding="utf-8")
    (tmp_path / "docs2" / "two.txt").write_text("2", encoding="utf-8")

    first = scope_id_for(locator_for(tmp_path / "docs"))
    second = scope_id_for(locator_for(tmp_path / "docs2"))
    assert first != second
    assert not second.startswith(first)
    assert _uris(tmp_path / "docs").isdisjoint(_uris(tmp_path / "docs2"))


def test_a_relative_root_is_refused_rather_than_resolved_against_the_cwd() -> None:
    """`canonical_uri` refuses a relative path and `locator_for` inherits the refusal.

    A `unit_uri` that depended on the process working directory would name a different file
    depending on where `ow` was invoked from, which is the bug 08-runtime.md section 1.3 bans
    `os.getcwd()` and `Path(".")` to prevent.
    """
    with pytest.raises(ValueError, match="relative"):
        locator_for(Path("docs"))


def test_a_symlinked_file_and_its_target_are_one_unit(
    tmp_path: Path,
    symlinks: None,  # noqa: ARG001 - the fixture is a skip guard, not a value
) -> None:
    """`realpath` resolves the link, so a link and its target are ONE `unit_uri` (05:239).

    Two directory entries, one unit: the walk emits two candidates and the host mints one uri.
    That is what makes 05:400 rule 5's `ON CONFLICT` upsert the convergence point rather than a
    race.
    """
    root = tmp_path / "corpus"
    root.mkdir()
    (root / "real.txt").write_text("body", encoding="utf-8")
    (root / "link.txt").symlink_to(root / "real.txt")

    candidates = _walk(root)
    assert {candidate.stable_id for candidate in candidates} == {"real.txt", "link.txt"}
    assert len(_uris(root)) == 1


def test_a_link_out_of_the_tree_is_refused_and_counted_not_silently_dropped(
    tmp_path: Path,
    symlinks: None,  # noqa: ARG001 - the fixture is a skip guard, not a value
) -> None:
    """05:70: *"`OW_PATH_OUTSIDE_ROOTS` (`OW-A-007`) is a refusal, not a warning."*

    The walk never leaves the tree, but `realpath` does -- so the containment test has to be on
    the minted uri and not on the walked path. The refusal is per unit: the scan continues, and
    the count lands in `skipped_why` where an operator can see it.
    """
    outside = tmp_path / "outside.txt"
    outside.write_text("elsewhere", encoding="utf-8")
    root = tmp_path / "corpus"
    root.mkdir()
    (root / "inside.txt").write_text("here", encoding="utf-8")
    (root / "escape.txt").symlink_to(outside)

    locator = locator_for(root)
    tally = Tally()
    rows = list(
        scan(
            locator,
            Scope(roots=(locator.target,)),
            IngestGuards(),
            indexed_at_ns=1,
            last_seen_gen=1,
            tally=tally,
        )
    )
    assert [row.unit_uri.rsplit("/", 1)[-1] for row in rows] == ["inside.txt"]
    assert tally.skipped_why == {"path_outside_roots": 1}
    assert tally.discovered == tally.indexed + tally.skipped == 2


@pytest.mark.skipif(not WINDOWS, reason="a directory junction is a Windows reparse point")
def test_a_directory_junction_and_its_target_are_one_scope(tmp_path: Path) -> None:
    """A Windows junction is the reparse point a user has without a privilege, and `realpath`
    resolves it -- so a tree reached through a junction is the SAME corpus, not a second copy.

    This is the case that makes the normalisation load-bearing on the platform W3.8's estimation
    basis singles out. Two enumerations, one through `real/` and one through `j/`, must mint the
    same `unit_uri` set and the same `scope_id`: two sets would double-bill the corpus, and two
    scope_ids would give one corpus two coverage rows for absence gate 4 to disagree over.
    """
    real = tmp_path / "real"
    (real / "docs").mkdir(parents=True)
    (real / "docs" / "one.txt").write_text("one", encoding="utf-8")
    junction = tmp_path / "j"
    # A fixed argv, no shell, no user input. `cmd` is deliberately unqualified: `mklink` is a
    # cmd BUILTIN, not an executable, so there is no absolute path to give.
    argv = ["cmd", "/c", "mklink", "/J", str(junction), str(real)]
    made = subprocess.run(argv, capture_output=True, text=True, check=False)  # noqa: S603
    if made.returncode != 0:  # pragma: no cover - depends on the machine
        pytest.skip(f"mklink /J is unavailable: {made.stderr.strip() or made.stdout.strip()}")

    assert _uris(junction) == _uris(real)
    assert scope_id_for(locator_for(junction)) == scope_id_for(locator_for(real))


def test_the_host_half_refuses_an_id_that_tries_to_re_root_itself(tree: Path) -> None:
    """A connector-supplied `id` may never be absolute: `identity.py:134-143`'s `_join_under`.

    `Path(root) / "/abs"` silently yields `/abs` in Python, which is how a hostile or buggy
    connector would walk out of `[roots] source` before any confinement check saw it.
    """
    locator = locator_for(tree)
    for hostile in ("/etc/passwd", "\\\\server\\share\\x", "c:/windows/system32/x"):
        with pytest.raises((ValueError, PolicyRefusal)):
            roster_row_of(
                locator,
                CandidateRecord(tmp="c/000001", stable_id=hostile),
                indexed_at_ns=1,
                last_seen_gen=1,
            )


def test_this_module_owns_no_second_normalisation() -> None:
    """The estimation basis names a second normaliser as the failure mode, so this checks.

    16-roadmap.md:527: the normalisation *"is the reason `canonical_uri()` is one function"*.
    A `realpath`, a `normcase`, a `.resolve()` or a `\\\\?\\` literal appearing in this module
    would be a second answer to a question that already has one, and the two would drift.
    Comments and docstrings are stripped first, per rule 3: a comment is not a definition site,
    and this module's docstrings quote all four spellings deliberately.
    """
    source = MODULE.read_text(encoding="utf-8")
    stripped = _strip_comments_and_docstrings(source)
    for banned in ("realpath", "normcase", ".resolve(", "\\\\?\\", "?\\\\"):
        assert banned not in stripped, f"acquire.py normalises a path itself: {banned!r}"
    assert stripped.count("canonical_uri(") == 2, (
        "canonical_uri is called at exactly two sites in this module: `locator_for` projects "
        "the root and `roster_row_of` mints the unit_uri"
    )


def _strip_comments_and_docstrings(source: str) -> str:
    """Executable source only: every string literal and comment removed.

    Rule 3 -- a comment is not a definition site -- applied mechanically, through `ast` rather
    than through a regular expression, so a `#` inside a string cannot fool it.
    """
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            node.value = ""
    return ast.unparse(tree)


# --------------------------------------------------------------------------------------------
# 2. The walk: order, cursor resumption, and every guard
# --------------------------------------------------------------------------------------------


def test_walk_order_is_not_string_order_and_the_walk_follows_walk_order(tree: Path) -> None:
    """The `a/b.txt` versus `a.txt` witness, in both halves.

    `"a.txt" < "a/b.txt"` as strings, because `.` (0x2E) sorts below `/` (0x2F) -- but the walk
    descends the directory `a` at the position of the name `"a"`, which is before `"a.txt"`. So
    the emission order is lexicographic on the SEGMENT TUPLE and not on the joined path, and a
    cursor compared as a string would skip or re-emit a run of files on every resume.
    """
    as_strings = sorted(["a.txt", "a/b.txt"])
    assert as_strings == ["a.txt", "a/b.txt"]
    assert walk_order("a/b.txt") < walk_order("a.txt")

    emitted = [candidate.stable_id for candidate in _walk(tree)]
    assert emitted.index("a/b.txt") < emitted.index("a.txt")
    assert emitted == sorted(emitted, key=walk_order)


def test_a_cursor_resumes_from_any_emitted_record(tree: Path) -> None:
    """05:208: `enumerate` *"**must** be resumable from any emitted `next_cursor`"*.

    Every cursor is tried, not one: resumption from record k must yield exactly records k+1..n,
    with no gap and no repeat. A gap is a lost document and a repeat is a doubled `bytes_read`.
    """
    full = _walk(tree)
    assert len(full) > 3
    for index, candidate in enumerate(full):
        assert candidate.next_cursor is not None
        resumed = _walk(tree, cursor=candidate.next_cursor)
        assert [item.stable_id for item in resumed] == [
            item.stable_id for item in full[index + 1 :]
        ], candidate.next_cursor


def test_a_cursor_names_the_relpath_and_the_inode(tree: Path) -> None:
    """`<relpath>\\0<inode>` -- 05:289's cell for `acquire.fs.local`, both halves present.

    The inode is the half `os.DirEntry.stat()` returns as 0 on Windows, so this is also the test
    that `_inode`'s extra `stat` actually runs there: a corpus of cursors all naming inode 0
    would make the second field decoration.

    **`inode != 0` is not the property, and asserting it pins nothing.** A `_inode` that returned
    the constant 1 for every entry satisfies "not zero" and is exactly as useless as returning 0:
    the second field exists to distinguish *"the file I stopped at"* from *"a different file since
    created at that path"*, which only a per-file value can do. So each cursor's inode is compared
    against `Path.stat()`'s -- a full stat BY PATH, which is the operating system as an
    independent source and not the `DirEntry` record `_inode` reads -- and the inodes are
    asserted distinct across the fixture's distinct files.
    """
    seen: dict[str, int] = {}
    for candidate in _walk(tree):
        assert candidate.next_cursor is not None
        relpath, separator, inode = candidate.next_cursor.partition(CURSOR_SEP)
        assert separator == CURSOR_SEP
        assert relpath == candidate.stable_id
        assert int(inode) > 0
        assert int(inode) == (tree / relpath).stat().st_ino, relpath
        seen[relpath] = int(inode)
    assert len(set(seen.values())) == len(seen), f"one inode for several files: {seen}"


def test_the_tmp_ids_are_dense_from_the_first_record(tree: Path) -> None:
    """05:133: the `tmp` address is *"unique within one `enumerate` and dense from `c/000001`"*.

    Dense is what lets the host detect a dropped line by arithmetic, so it is asserted as an
    exact sequence rather than as a uniqueness property.

    `TMP_FIRST` is tied to the emitted id in the same breath, because `iter_candidates` builds
    `f"c/{emitted:06d}"` and never reads the constant: the two are free to drift, and the literal
    `"c/000001"` is what 05:151 actually prints.
    """
    candidates = _walk(tree)
    assert [candidate.tmp for candidate in candidates] == [
        f"c/{n:06d}" for n in range(1, len(candidates) + 1)
    ]
    assert candidates[0].tmp == "c/000001" == acquire.TMP_FIRST


def test_the_shipped_exclude_default_excludes_a_root_level_node_modules(tree: Path) -> None:
    """Both directions of the `**/` relaxation `in_scope` documents.

    `fnmatch` translates `**/node_modules/**` to `.*/node_modules/.*`, which does not match
    `node_modules/react/index.js` at the top of the scope root -- so without the relaxation the
    shipped default (05:436) fails to exclude the very directory it names. And the other
    direction: `nodemodules/keep.txt` is NOT excluded, because the pattern names a segment and
    not a prefix of one. A positive list alone would only have proved the pattern wide enough.
    """
    emitted = {candidate.stable_id for candidate in _walk(tree)}
    assert "node_modules/react/index.js" not in emitted
    assert "nodemodules/keep.txt" in emitted


def test_a_dotted_path_is_excluded_unless_an_include_names_the_segment_literally(
    tree: Path,
) -> None:
    """05:447: `hidden = false` excludes a dotfile *"unless named explicitly"*.

    The distinction that makes that sentence mean something is literal versus wildcard: a caller
    writing `include = [".hidden/**"]` asked for it; a caller writing `**/*` did not.
    """
    default = {candidate.stable_id for candidate in _walk(tree)}
    assert ".hidden/secret.txt" not in default

    named = {candidate.stable_id for candidate in _walk(tree, include=(".hidden/**",))}
    assert named == {".hidden/secret.txt"}

    wildcard = {candidate.stable_id for candidate in _walk(tree, include=("*/secret.txt",))}
    assert wildcard == set()


def test_exclude_wins_over_include() -> None:
    """An `include` of `**/*` matches everything the shipped `exclude` list names.

    So the two cannot be commutative: 05:436's `exclude` is a list of things that must not be
    indexed, and a first-match-wins-by-include reading would index all of them.
    """
    assert in_scope("keep.txt", Scope(roots=("x",), include=("**/*",), exclude=()), IngestGuards())
    assert not in_scope(
        "keep.txt",
        Scope(roots=("x",), include=("**/*",), exclude=("keep.txt",)),
        IngestGuards(),
    )


def test_max_depth_bounds_the_walk_and_a_root_level_file_is_depth_one(tree: Path) -> None:
    """`[ingest] max_depth = 32` (05:438); `walk_depth` is the segment count (05:132).

    05:132's own example record reads `"labels":{"walk_depth":2}` for `docs/q3-10k.pdf`, which
    fixes the origin: a file directly in the root is depth 1, not 0.
    """
    locator = locator_for(tree)
    scope = Scope(roots=(locator.target,))
    shallow = tuple(iter_candidates(locator, scope, IngestGuards(max_depth=1), tally=Tally()))
    assert {candidate.stable_id for candidate in shallow} == {"a.txt", "readme.md"}
    assert {candidate.labels["walk_depth"] for candidate in shallow} == {1}

    deep = {candidate.stable_id: candidate.labels["walk_depth"] for candidate in _walk(tree)}
    assert deep["docs/q3.pdf"] == 2
    assert deep["docs/reports/deep.txt"] == 3


def test_a_walk_is_deterministic_over_a_shuffled_directory_listing(tree: Path) -> None:
    """The filesystem's `scandir` order is not a contract, so the walk sorts.

    Two enumerations of one tree must be byte-identical or the cursor means nothing and two runs
    write two different rosters. The injected `scandir` returns each directory reversed, which is
    the cheapest witness that the sort is the walk's and not the filesystem's.
    """
    locator = locator_for(tree)
    scope = Scope(roots=(locator.target,))

    def reversed_scandir(path: str) -> list[os.DirEntry[str]]:
        return sorted(os.scandir(path), key=lambda item: item.name, reverse=True)

    forward = [item.stable_id for item in _walk(tree)]
    shuffled = [
        item.stable_id
        for item in iter_candidates(
            locator, scope, IngestGuards(), tally=Tally(), scandir=reversed_scandir
        )
    ]
    assert forward == shuffled


def test_a_symlinked_directory_is_neither_descended_nor_indexed_by_default(
    tmp_path: Path,
    symlinks: None,  # noqa: ARG001 - the fixture is a skip guard, not a value
) -> None:
    """`[ingest] follow_symlinks = false` (05:443) bounds the walk, and BOTH of its consequences.

    05:77-78 is the reason the default is `false`: *"a symlink in an untrusted tree is the
    cheapest way out of `[roots] source`"*. The link here points at the very root that contains
    it, which is the cycle a walk that ignored the guard would follow forever, so this asserts
    three things that were each unobserved before:

    1. the linked directory is NOT descended -- flipping `_walk`'s `follow_symlinks` argument to
       a hard `True` changes nothing else any test looks at;
    2. the link is not a *candidate* either. `entry.is_dir(follow_symlinks=False)` is false for a
       directory symlink, so without `_walk`'s explicit clause the link falls through to the
       `yield`, `canonical_uri` resolves it, and the roster acquires a `unit` row for a DIRECTORY;
    3. with the guard on, the walk still TERMINATES -- `max_depth` is the only bound on a cycle,
       so the deepest emitted path has exactly `max_depth` segments and no path repeats.
    """
    root = tmp_path / "corpus"
    (root / "sub").mkdir(parents=True)
    (root / "sub" / "leaf.txt").write_text("leaf", encoding="utf-8")
    (root / "loop").symlink_to(root, target_is_directory=True)

    locator = locator_for(root)
    scope = Scope(roots=(locator.target,))
    tally = Tally()
    guarded = tuple(iter_candidates(locator, scope, IngestGuards(), tally=tally))
    assert [candidate.stable_id for candidate in guarded] == ["sub/leaf.txt"]
    assert (tally.discovered, tally.skipped) == (1, 0)

    followed = [
        candidate.stable_id
        for candidate in iter_candidates(
            locator, scope, IngestGuards(follow_symlinks=True, max_depth=4), tally=Tally()
        )
    ]
    assert followed == ["loop/loop/sub/leaf.txt", "loop/sub/leaf.txt", "sub/leaf.txt"]
    assert max(len(walk_order(stable)) for stable in followed) == 4
    assert len(followed) == len(set(followed))


def test_in_scope_bounds_the_depth_at_max_depth_and_not_one_past_it() -> None:
    """`[ingest] max_depth = 32` (05:444), asserted on the guard and not only on the walk.

    Two functions apply the bound: `_walk` stops pushing a directory at `depth < max_depth`, and
    `in_scope` refuses a path with more than `max_depth` segments. The walk's own bound means
    `in_scope` never sees a too-deep path in production -- which is exactly why an off-by-one
    there is invisible from `iter_candidates` and has to be tested here. `in_scope` is exported
    (`__all__`) and 05:108 makes it *"the authoritative guard"*, so the host may call it on a
    path a driver proposed rather than one this walk produced.

    A root-level file is depth 1 (05:140's `walk_depth`), so `max_depth = 2` admits `a/b.txt`
    and refuses `a/b/c.txt`.
    """
    scope = Scope(roots=("c:/x",))
    guards = IngestGuards(max_depth=2)
    assert in_scope("b.txt", scope, guards)
    assert in_scope("a/b.txt", scope, guards)
    assert not in_scope("a/b/c.txt", scope, guards)
    assert not in_scope("a/b/c/d.txt", scope, guards)


# --------------------------------------------------------------------------------------------
# 3. The stat triple: the capture ORDER, and the freshness predicate
# --------------------------------------------------------------------------------------------


def test_the_stat_triple_is_the_one_captured_before_the_content_read(tmp_path: Path) -> None:
    """02-architecture.md:472 -- *"captured **before** the content read"* -- observed as an ORDER.

    The injected reader appends to the file before returning its bytes, which is a writer racing
    the read. A correct implementation returns the triple as the file was; a stat-after-read
    implementation returns the grown size and the new mtime, and the next incremental run then
    reports `stat_fresh` against the torn copy it stored and never re-reads the document.

    Asserting the triple's values against a separate `stat` would not distinguish the two.
    """
    path = tmp_path / "racing.txt"
    path.write_text("before", encoding="utf-8")
    original = path.stat()

    def mutating_read(target: Path, limit: int) -> bytes:
        body = target.read_bytes()[:limit]
        with target.open("ab") as handle:
            handle.write(b" and after")
        os.utime(target, ns=(original.st_atime_ns, original.st_mtime_ns + 5_000_000_000))
        return body

    triple, body = fetch_local(path, indexed_at_ns=99, read=mutating_read)

    assert body == b"before"
    assert triple == StatTriple(size=6, mtime_ns=original.st_mtime_ns, indexed_at_ns=99)
    after = path.stat()
    assert after.st_size == 16
    assert triple.size != after.st_size
    assert triple.mtime_ns != after.st_mtime_ns


def test_the_bounded_read_refuses_at_the_limit_plus_one_byte(tmp_path: Path) -> None:
    """05:330-332 mechanism 2, and the extra byte is the whole mechanism.

    Reading exactly `limit` cannot tell a file of `limit` bytes from a file of a terabyte, which
    is the `size = null` case and the lying-`Content-Length` case. The `limit` field names the
    knob an operator would raise.
    """
    path = tmp_path / "big.bin"
    path.write_bytes(b"x" * 33)

    triple, body = fetch_local(path, indexed_at_ns=1, max_unit_bytes=33)
    assert len(body) == 33
    assert triple.size == 33

    with pytest.raises(DriverError) as caught:
        fetch_local(path, indexed_at_ns=1, max_unit_bytes=32)
    assert caught.value.cls is FailureClass.TOO_LARGE
    assert caught.value.limit == "ingest.max_unit_bytes"


def test_stat_fresh_needs_all_three_clauses() -> None:
    """The ladder's zero-byte rung, clause by clause. 05:337-347.

    Literals, not constants imported from the subject: the granularity window is two seconds
    because 05:339 writes `MTIME_GRANULARITY_NS(2e9)`, and a test that read the number off
    `acquire.MTIME_GRANULARITY_NS` would pin agreement rather than value.
    """
    mtime = 1_700_000_000_000_000_000
    settled = StatTriple(size=10, mtime_ns=mtime, indexed_at_ns=mtime + 2_000_000_000)
    observed = StatTriple(size=10, mtime_ns=mtime, indexed_at_ns=0)

    assert stat_fresh(settled, observed)
    assert not stat_fresh(settled, observed._replace(size=11))
    assert not stat_fresh(settled, observed._replace(mtime_ns=mtime + 1))

    # Clause 3: indexed one nanosecond inside the granularity window. The bytes and the mtime
    # agree and the unit is STILL not fresh, because a file rewritten in place with an identical
    # size inside one mtime tick cannot be proven unchanged (05:341-343, :350).
    racing = StatTriple(size=10, mtime_ns=mtime, indexed_at_ns=mtime + 1_999_999_999)
    assert not stat_fresh(racing, observed)

    exactly = StatTriple(size=10, mtime_ns=mtime, indexed_at_ns=mtime + 2_000_000_000)
    assert stat_fresh(exactly, observed)


def test_the_granularity_window_is_two_seconds() -> None:
    """`MTIME_GRANULARITY_NS(2e9)` -- 05:339 and `0004_runtime.sql:84`, as a literal."""
    assert acquire.MTIME_GRANULARITY_NS == 2_000_000_000


# --------------------------------------------------------------------------------------------
# 4. The roster: the upsert's SET list, the batching, and the transaction the coverage row is in
# --------------------------------------------------------------------------------------------


def test_the_roster_upsert_refreshes_last_seen_gen_and_cursor_and_nothing_else() -> None:
    """05:395-398 rule 5, asserted on the statement rather than on its effect.

    The `SET` list is what stops the enumerator re-stamping the stored stat triple. A widened
    `SET` list would break nothing that any single test observes and would make every unit
    permanently `stat_fresh`, so the statement itself is pinned.
    """
    set_clause = acquire.UNIT_UPSERT_SQL.split("DO UPDATE SET", 1)[1]
    # Split on the assignments and not on every comma: `max(last_seen_gen, excluded....)` holds
    # one of its own, and a naive split would count the argument as a third assigned column.
    assigned = {target.strip() for target in re.findall(r"(?:^|,)\s*([a-z_]+)\s*=", set_clause)}
    assert assigned == {"last_seen_gen", "cursor"}
    assert "max(last_seen_gen, excluded.last_seen_gen)" in set_clause
    assert "ON CONFLICT(unit_uri)" in acquire.UNIT_UPSERT_SQL
    assert tuple(acquire.UNIT_COLUMNS) == DISCOVERED_COLUMNS


def test_a_rescan_does_not_overwrite_the_stored_stat_triple(
    store: ow.StoreThread, tmp_path: Path
) -> None:
    """The consequence of that `SET` list, through a real store and a real second scan.

    A file is rostered, then modified, then re-scanned at a later generation. `last_seen_gen` and
    `cursor` move; `size`, `mtime_ns` and `indexed_at_ns` do not -- because `stat_fresh` compares
    the STORED triple against a fresh `stat`, and an enumerator that re-stamped the stored one
    would compare the fresh stat against itself, report fresh for every unit forever, and never
    re-index a changed document again.
    """
    root = tmp_path / "corpus"
    root.mkdir()
    target = root / "one.txt"
    target.write_text("first", encoding="utf-8")
    locator = locator_for(root)
    scope = Scope(roots=(locator.target,))

    def one_scan(*, indexed_at_ns: int, generation: int) -> None:
        tally = Tally()
        rows = scan(
            locator,
            scope,
            IngestGuards(),
            indexed_at_ns=indexed_at_ns,
            last_seen_gen=generation,
            tally=tally,
        )
        write_roster(
            store, rows, tally=tally, scope_id=scope_id_for(locator), scanned_at_ns=indexed_at_ns
        )

    one_scan(indexed_at_ns=100, generation=1)
    first = _unit_row(store, next(iter(_uris(root))))

    target.write_text("second, longer", encoding="utf-8")
    os.utime(target, ns=(first["mtime_ns"] + 10**10, first["mtime_ns"] + 10**10))
    one_scan(indexed_at_ns=200, generation=2)
    second = _unit_row(store, next(iter(_uris(root))))

    assert second["last_seen_gen"] == 2
    assert (second["size"], second["mtime_ns"], second["indexed_at_ns"]) == (
        first["size"],
        first["mtime_ns"],
        first["indexed_at_ns"],
    )
    assert second["indexed_at_ns"] == 100
    assert second["state"] == "discovered"


def test_a_rescan_never_lowers_last_seen_gen(store: ow.StoreThread, tmp_path: Path) -> None:
    """`max(last_seen_gen, excluded.last_seen_gen)` -- 05:398's own function.

    05:401: *"two `ow ingest` processes over the same scope converge instead of racing, and
    neither resets a state machine the other advanced"*. A late-arriving older generation must
    not lower the stamp, or 05:365's deletion rule would mark a unit `out_of_scope` that the
    newer run had just seen.
    """
    root = tmp_path / "corpus"
    root.mkdir()
    (root / "one.txt").write_text("body", encoding="utf-8")
    locator = locator_for(root)
    scope = Scope(roots=(locator.target,))
    uri = next(iter(_uris(root)))

    for generation in (9, 3):
        tally = Tally()
        write_roster(
            store,
            scan(
                locator,
                scope,
                IngestGuards(),
                indexed_at_ns=1,
                last_seen_gen=generation,
                tally=tally,
            ),
            tally=tally,
            scope_id=scope_id_for(locator),
        )
    assert _unit_row(store, uri)["last_seen_gen"] == 9


def _unit_row(thread: ow.StoreThread, unit_uri: str) -> dict[str, object]:
    """One `unit` row as a mapping, read through the store thread."""

    def run(connection: sqlite3.Connection) -> dict[str, object]:
        columns = ", ".join(DISCOVERED_COLUMNS)
        row = connection.execute(
            f"SELECT {columns} FROM unit WHERE unit_uri = ?",  # noqa: S608 - a fixed tuple
            (unit_uri,),
        ).fetchone()
        assert row is not None, unit_uri
        return dict(zip(DISCOVERED_COLUMNS, row, strict=True))

    return thread.run(ow.Unit(name="test read", run=run))  # type: ignore[return-value]


def test_the_roster_commits_at_512_rows_per_transaction() -> None:
    """`[runtime] plan_batch = 512` (02-architecture.md:472), as a literal and as a boundary.

    1,025 rows are 3 transactions of 512, 512 and 1 -- so the assertion is on the sizes and not
    only on the count, which is what distinguishes batching from one big statement.
    """
    assert acquire.PLAN_BATCH == 512
    thread = RecordingThread()
    rows = [_row(f"c:/x/{n}.txt") for n in range(1025)]
    written, coverage = write_roster(thread, rows)  # type: ignore[arg-type]
    assert written == 1025
    assert coverage is None
    assert thread.batch_sizes == [512, 512, 1]
    assert thread.wait_ms == [60_000, 60_000, 60_000]


def test_the_coverage_row_lands_in_the_same_transaction_as_the_last_roster_batch() -> None:
    """02-architecture.md:472's *"plus one `ingest_scope` row"*, placed rather than merely written.

    A coverage row in a second transaction leaves a window in which the roster is complete and
    the store still has no scope row -- and 07 section 3.8's absence rule reads that window as
    "coverage UNKNOWN", which is a `DEGRADED` verdict on a corpus that is fine. So the last
    transaction must carry both statements, and no earlier one may carry the scope row.
    """
    thread = RecordingThread()
    tally = Tally()
    for _ in range(600):
        tally.discover()
        tally.roster()
    tally.finish()
    written, coverage = write_roster(
        thread,  # type: ignore[arg-type]
        [_row(f"c:/x/{n}.txt") for n in range(600)],
        tally=tally,
        scope_id="c:/x/",
        scanned_at_ns=7,
    )
    assert written == 600
    assert coverage is not None
    assert coverage.complete is True
    assert len(thread.transactions) == 2
    assert all("ingest_scope" not in sql for sql in thread.transactions[0])
    last = thread.transactions[-1]
    assert len(last) == 2
    assert "INSERT INTO unit" in last[0]
    assert "INSERT INTO ingest_scope" in last[1]


def test_a_single_batch_write_is_one_transaction_for_ow_add() -> None:
    """05:411 rule 1: *"writes `unit` rows plus one `ingest_scope` row in a single transaction"*.

    Enqueue-before-lock (charter section 5 X31) needs both in one commit, so that a caller dying
    between them loses the drain and never the work. A caller gets it by passing a `plan_batch`
    no smaller than the row count -- which is what `ow_add` does and a corpus scan does not.
    """
    thread = RecordingThread()
    tally = Tally()
    tally.discover()
    tally.roster()
    tally.finish()
    write_roster(
        thread,  # type: ignore[arg-type]
        [_row("c:/x/1.txt")],
        tally=tally,
        scope_id="c:/x/",
        plan_batch=512,
    )
    assert len(thread.transactions) == 1
    assert len(thread.transactions[0]) == 2


def test_a_tally_without_a_scope_id_is_refused() -> None:
    """An `ingest_scope` row is keyed by its `scope_id`; a tally without one has nowhere to land."""
    thread = RecordingThread()
    with pytest.raises(ValueError, match="scope_id"):
        write_roster(thread, (), tally=Tally())  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="scope_id"):
        write_roster(thread, (), scope_id="c:/x/")  # type: ignore[arg-type]


def test_an_unmigrated_store_is_refused_by_name(tmp_path: Path) -> None:
    """The roster writer names the two tables it needs rather than failing per statement."""
    path = tmp_path / "empty.owstore"
    with (
        ow.StoreThread(lambda: ow.connect(path)) as thread,
        pytest.raises(StoreError, match="ingest_scope, unit"),
    ):
        acquire.refuse_unmigrated(thread)


def _row(unit_uri: str) -> RosterRow:
    """A minimal `RosterRow` for the writer's own tests."""
    return RosterRow(
        unit_uri=unit_uri,
        cursor=None,
        stat=StatTriple(size=1, mtime_ns=2, indexed_at_ns=3),
        trust_class=TrustClass.INTERNAL,
        last_seen_gen=1,
    )


# --------------------------------------------------------------------------------------------
# 5. `ingest_scope`: the arithmetic, the reasons, and completeness
# --------------------------------------------------------------------------------------------


def test_a_coverage_row_that_loses_a_document_cannot_be_constructed() -> None:
    """`discovered == indexed + skipped`. A scan that discovers 100 and rosters 60 lost 40.

    07:2184's absence gate 4 fires on `discovered > indexed`, so the difference is exactly the
    number the gate is reporting -- and a row where that difference is unaccounted for is a gate
    firing with no reason attached to it.
    """
    with pytest.raises(ValueError, match="discovered 100"):
        ScopeTally(
            scope_id="c:/x/",
            discovered=100,
            indexed=60,
            skipped=0,
            scanned_at_ns=1,
            complete=True,
        )
    balanced = ScopeTally(
        scope_id="c:/x/",
        discovered=100,
        indexed=60,
        skipped=40,
        skipped_why={"too_large": 40},
        scanned_at_ns=1,
        complete=True,
    )
    assert balanced.discovered == balanced.indexed + balanced.skipped


def test_every_skip_carries_its_reason() -> None:
    """05:773: *"that member is skipped and **counted** in `ingest_scope.skipped_why`"*.

    Both directions: a `skipped` count with no reasons behind it is refused, and a reason outside
    this connector's three is refused at the accumulator rather than written as free text.
    """
    with pytest.raises(ValueError, match="skipped_why sums to 0"):
        ScopeTally(
            scope_id="c:/x/", discovered=1, indexed=0, skipped=1, scanned_at_ns=1, complete=True
        )
    tally = Tally()
    with pytest.raises(ValueError, match="not one of"):
        tally.skip("because_i_said_so")


def test_a_too_large_file_is_skipped_before_any_fetch_and_counted(tmp_path: Path) -> None:
    """05:325-330 mechanism 1: refused *"**before** calling `fetch`"*, so no blob is written.

    The evidence that no read happened is the candidate stream itself -- the file never becomes a
    candidate, so nothing downstream can open it -- plus the reason landing in `skipped_why`.
    """
    root = tmp_path / "corpus"
    root.mkdir()
    (root / "small.txt").write_bytes(b"x" * 10)
    (root / "large.txt").write_bytes(b"x" * 5000)

    locator = locator_for(root)
    scope = Scope(roots=(locator.target,))
    guards = IngestGuards(max_unit_bytes=1000)

    candidates = Tally()
    emitted = tuple(iter_candidates(locator, scope, guards, tally=candidates))
    assert [candidate.stable_id for candidate in emitted] == ["small.txt"]
    assert candidates.skipped_why == {"too_large": 1}
    assert candidates.discovered == 2

    # The coverage row is the host half's, so it is frozen off a full `scan()`: `iter_candidates`
    # counts discoveries and skips, and only `scan()` can count what was rostered.
    scanned = Tally()
    rows = tuple(scan(locator, scope, guards, indexed_at_ns=1, last_seen_gen=1, tally=scanned))
    row = scanned.freeze(scope_id_for(locator), scanned_at_ns=1)
    assert len(rows) == 1
    assert (row.discovered, row.indexed, row.skipped) == (2, 1, 1)
    assert row.skipped_why == {"too_large": 1}


def test_a_truncated_scan_never_claims_complete(tree: Path) -> None:
    """05:371: *"An **incomplete** scan never marks anything out of scope."*

    `max_units_per_call` is what makes a million-file tree 200 invocations (05:210), and each one
    that stops early must say so -- otherwise `complete = 1` licenses the deletion pass to mark
    every unit the truncated scan did not reach as `out_of_scope`.
    """
    locator = locator_for(tree)
    scope = Scope(roots=(locator.target,))

    truncated = Tally()
    partial = tuple(
        scan(
            locator,
            scope,
            IngestGuards(),
            indexed_at_ns=1,
            last_seen_gen=1,
            tally=truncated,
            max_units=2,
        )
    )
    assert len(partial) == 2
    assert truncated.complete is False
    assert truncated.freeze(scope_id_for(locator), scanned_at_ns=1).complete is False

    whole = Tally()
    tuple(scan(locator, scope, IngestGuards(), indexed_at_ns=1, last_seen_gen=1, tally=whole))
    assert whole.complete is True


def test_the_coverage_row_serialises_skipped_why_deterministically() -> None:
    """Two runs over one tree must write byte-identical rows or `ow store diff` lies.

    `skipped_why` is a JSON map in a TEXT column, so the key order has to be the map's and not
    the insertion order that happened to occur.
    """
    forward = Tally()
    backward = Tally()
    for reason in ("too_large", "unreadable", "path_outside_roots"):
        forward.discover()
        forward.skip(reason)
    for reason in ("path_outside_roots", "unreadable", "too_large"):
        backward.discover()
        backward.skip(reason)
    first = forward.freeze("c:/x/", scanned_at_ns=5).params()
    second = backward.freeze("c:/x/", scanned_at_ns=5).params()
    assert first == second
    assert first["skipped_why"] == ('{"path_outside_roots":1,"too_large":1,"unreadable":1}')
    assert first["complete"] == 0


def test_the_three_counters_survive_a_round_trip_through_a_real_store(
    store: ow.StoreThread, tree: Path
) -> None:
    """The whole path, once, against the shipped DDL: the row read back is the row computed."""
    locator = locator_for(tree)
    tally = Tally()
    rows = scan(
        locator,
        Scope(roots=(locator.target,)),
        IngestGuards(),
        indexed_at_ns=42,
        last_seen_gen=3,
        tally=tally,
    )
    written, coverage = write_roster(
        store, rows, tally=tally, scope_id=scope_id_for(locator), scanned_at_ns=42
    )
    assert coverage is not None

    def run(connection: sqlite3.Connection) -> tuple[object, ...]:
        row = connection.execute(
            "SELECT discovered, indexed, skipped, skipped_why, scanned_at_ns, complete "
            "FROM ingest_scope WHERE scope_id = ?",
            (scope_id_for(locator),),
        ).fetchone()
        units = connection.execute("SELECT count(*) FROM unit").fetchone()[0]
        return (*row, units)

    discovered, indexed, skipped, why, scanned, complete, units = store.run(
        ow.Unit(name="test read", run=run)
    )  # type: ignore[misc]
    assert (discovered, indexed, skipped) == (
        coverage.discovered,
        coverage.indexed,
        coverage.skipped,
    )
    assert discovered == indexed + skipped
    assert units == indexed == written
    assert (why, scanned, complete) == ("{}", 42, 1)


def _scope_row(thread: ow.StoreThread, scope_id: str) -> tuple[object, ...]:
    """The `ingest_scope` row for one prefix, and proof that there is exactly one of it."""

    def run(connection: sqlite3.Connection) -> tuple[object, ...]:
        rows = connection.execute(
            "SELECT discovered, indexed, skipped, skipped_why, scanned_at_ns, complete "
            "FROM ingest_scope WHERE scope_id = ?",
            (scope_id,),
        ).fetchall()
        assert len(rows) == 1, rows
        return tuple(rows[0])

    return thread.run(ow.Unit(name="test read", run=run))  # type: ignore[return-value]


def test_a_second_scan_replaces_the_coverage_row_instead_of_merging_it(
    store: ow.StoreThread, tmp_path: Path
) -> None:
    """`ingest_scope` is a statement about the LAST scan of that prefix, so every column moves.

    `SCOPE_UPSERT_SQL`'s `ON CONFLICT` list had no test at all, in either direction. Replacing
    `complete = excluded.complete` with `complete = max(complete, excluded.complete)`, or
    `discovered = excluded.discovered` with `discovered = discovered + excluded.discovered`, left
    the whole file green -- because nothing wrote a second coverage row for one `scope_id`.

    The `complete` half is the one that bites: 05:372 (*"An **incomplete** scan never marks
    anything out of scope"*) is enforced by READING that column, so an interrupted scan that
    inherited a previous run's `complete = 1` re-licenses the deletion pass over every unit the
    interrupted scan never reached. And a summed `discovered` would report a figure no single
    scan saw, to a gate (07:2184) whose whole job is comparing it with `indexed`.

    Three files, one whole scan, then a `max_units = 1` scan of the same prefix. The tuples are
    the fixture's own counts, as literals: (3, 3, 0, complete) becomes (1, 1, 0, incomplete).
    """
    root = tmp_path / "corpus"
    root.mkdir()
    for name in ("one.txt", "three.txt", "two.txt"):
        (root / name).write_text(name, encoding="utf-8")
    locator = locator_for(root)
    scope = Scope(roots=(locator.target,))
    scope_id = scope_id_for(locator)

    def one_scan(*, max_units: int, at_ns: int) -> None:
        tally = Tally()
        rows = scan(
            locator,
            scope,
            IngestGuards(),
            indexed_at_ns=at_ns,
            last_seen_gen=1,
            tally=tally,
            max_units=max_units,
        )
        write_roster(store, rows, tally=tally, scope_id=scope_id, scanned_at_ns=at_ns)

    one_scan(max_units=100, at_ns=100)
    assert _scope_row(store, scope_id) == (3, 3, 0, "{}", 100, 1)

    one_scan(max_units=1, at_ns=200)
    assert _scope_row(store, scope_id) == (1, 1, 0, "{}", 200, 0)


# --------------------------------------------------------------------------------------------
# 6. The driver half: obligations 2 and 3, and structural conformance to `AcquireV1`
# --------------------------------------------------------------------------------------------


def test_a_candidate_record_carries_no_host_owned_key(tree: Path) -> None:
    """04 section 1.5 obligation 2, and 05:161-176's four absent key classes.

    *"no `block_id`, `unit_uri`, `segment_id` or `entity_id` ever crosses the wire from a
    driver"* -- so the record's key set is asserted exactly, in both directions: every key the
    plan prints is present, and no key it says the host owns can appear.
    """
    candidates = _walk(tree)
    assert candidates
    for candidate in candidates:
        record = candidate.record()
        assert set(record) == {
            "t",
            "tmp",
            "id",
            "connector",
            "next_cursor",
            "size",
            "mtime_ns",
            "etag",
            "media_type_hint",
            "labels",
        }
        assert record["t"] == "candidate"
        assert record["connector"] == "fs"
    forbidden = {"unit_uri", "trust_class", "state", "gen", "last_seen_gen", "cost_micros"}
    assert forbidden.isdisjoint(set(CandidateRecord.__dataclass_fields__))


def test_the_driver_half_cannot_mint_a_unit_uri(tree: Path) -> None:
    """The seam, asserted on the wire bytes an `enumerate` actually produces.

    A driver that minted a `unit_uri` would be wrong (05:152, obligation 2). This walks the real
    tree through `FsLocal.enumerate`, decodes every NDJSON line, and asserts that no value in any
    record is the `unit_uri` the host mints for that same file -- so the test would fail even if
    the record smuggled the uri under some other key.
    """
    locator = locator_for(tree)
    io = FakeIO()
    result = FsLocal().enumerate(locator, io)

    assert result.outcome == "ok"
    assert len(result.produced) == 1
    body = result.produced[0].inline
    assert body is not None
    records = [json.loads(line) for line in body.decode("utf-8").splitlines()]
    assert records

    host_minted = _uris(tree)
    assert host_minted
    for record in records:
        values = {value for value in record.values() if isinstance(value, str)}
        assert values.isdisjoint(host_minted)
        assert (
            record["id"] in {uri.rsplit("/", 1)[-1] for uri in host_minted} or "/" in record["id"]
        )


def test_the_host_stamps_trust_class_and_the_record_cannot(tree: Path) -> None:
    """Obligation 3 (05:110, :172): *"The host stamps `unit.trust_class`"*.

    05:112-118 is the consequence -- *"a connector can neither raise nor lower its own audit
    sample"* -- so the value must come from the caller's argument and from nowhere on the record.
    `0004_runtime.sql:76` gives the column NOT NULL with no DEFAULT for exactly this reason.
    """
    locator = locator_for(tree)
    candidate = _walk(tree)[0]
    for wanted in TrustClass:
        row = roster_row_of(
            locator, candidate, indexed_at_ns=1, last_seen_gen=1, trust_class=wanted
        )
        assert row.trust_class is wanted
        assert row.params()["trust_class"] == wanted.value


def test_fetch_puts_the_bytes_in_the_cas_and_the_record_names_them(tmp_path: Path) -> None:
    """04 section 1.4: *"Materialise one unit's bytes into the CAS. Idempotent on
    `content_sha256`."*

    Three claims, one call. The bytes go through `io.blobs.put()` and not onto the wire; the
    record names the blob by `blob_ref` and carries no identity of its own -- 05:184, *"`fetched`
    therefore carries no identity at all"*; and a second `fetch` of an unchanged file produces
    the same digest, which is what makes it idempotent rather than merely repeatable.

    `content_sha256 == source_sha256` because 05:271's normaliser table gives *"everything else |
    none | raw bytes are hashed"* -- an fs connector identifies no format and chooses no
    normaliser.
    """
    path = tmp_path / "unit.txt"
    path.write_bytes(b"the body")
    ref = UnitRef(
        uri=str(path).replace("\\", "/"),
        part="",
        content_sha256=hashlib.sha256(b"the body").hexdigest(),
        byte_len=8,
        media_type="text/plain",
    )

    driver = FsLocal()
    first = driver.fetch(ref, FakeIO())
    second_io = FakeIO()
    second = driver.fetch(ref, second_io)

    body = first.produced[0].inline
    assert body is not None
    record = json.loads(body.decode("utf-8"))
    assert record["t"] == "fetched"
    assert set(record) == {
        "t",
        "content_sha256",
        "source_sha256",
        "bytes",
        "blob_ref",
        "media_type_hint",
        "etag",
        "fetched_at_ns",
    }
    assert record["content_sha256"] == record["source_sha256"] == ref.content_sha256
    assert record["bytes"] == 8
    assert record["blob_ref"] == f"cas://{ref.content_sha256}"
    assert second_io.puts == [b"the body"]
    assert first.produced[0].inline == second.produced[0].inline
    assert first.metrics.bytes_read == 8

    # No identity: neither the unit_uri the host would mint nor any roster column appears.
    assert "unit_uri" not in record
    values = {value for value in record.values() if isinstance(value, str)}
    assert ref.uri not in values


def test_fs_local_satisfies_the_acquire_protocol_signature_for_signature() -> None:
    """Structural conformance to `AcquireV1`, compared by signature and not by `isinstance`.

    04 section 1.4 prints the four Port protocols as plain `Protocol`s, and
    `store/__init__.py`'s docstring gives the reason `@runtime_checkable` would not help:
    `isinstance` against a Protocol checks that the ATTRIBUTES exist and never their signatures,
    and the thing a driver must actually get right is the signatures.

    The parameter KINDS are compared beside the names, because a name list alone accepts a
    `def enumerate(self, locator, *, io)` that no host would ever be able to call positionally --
    which is the one signature drift `inspect` can see and a name list cannot.

    `SCHEMA_VERSION` is pinned to the literal `1` rather than to `isinstance(..., int)`. It is
    *"the only driver version that enters a cache key"* (04:1478) and `activate()` refuses a
    `CARD_CODE_MISMATCH` when the loaded class disagrees with the card (04:1544); both of 04's
    worked cards print `schema_version = 1` (04:869, :1612), and 04:2403 says it moves only when
    a driver's output bytes change for the same input. Nothing has changed them, so it is 1, and
    `isinstance(x, int)` would have accepted a silent bump that invalidated every cached roster.
    """
    for name in ("probe", "__init__", "enumerate", "fetch"):
        expected = inspect.signature(getattr(AcquireV1, name))
        actual = inspect.signature(getattr(FsLocal, name))
        assert list(actual.parameters) == list(expected.parameters), name
        assert [param.kind for param in actual.parameters.values()] == [
            param.kind for param in expected.parameters.values()
        ], name
    assert FsLocal.PORT == "acquire/1"
    assert FsLocal.SCHEMA_VERSION == 1


class _HostileEnv:
    """A `ProbeEnv` stand-in that raises on every attribute read.

    The only way to observe "the probe reads nothing off `env`" is to make reading fail. A real
    `ProbeEnv` cannot do that -- it is a frozen dataclass whose fields answer -- so the double is
    shaped like one and refuses.
    """

    def __getattr__(self, name: str) -> object:
        raise AssertionError(
            f"FsLocal.probe read env.{name}: the verdict is cached per "
            f"(driver_id, version, card_sha256, env_digest) and nothing else may enter it"
        )


def test_the_probe_reads_nothing_off_env_and_calls_nothing_but_its_verdict() -> None:
    """04 section 1.4: a probe *"MUST NOT download, spawn or write"*.

    It also must not answer "is this corpus present": the verdict is cached per
    `(driver_id, version, card_sha256, env_digest)`, and a corpus is not a member of that key.

    **Both halves used to be untested and the docstring said otherwise.** The previous version
    stat'ed `tmp_path` before and after the call and compared -- an assertion over an EMPTY
    collection, since `tmp_path` starts empty and `FsLocal.probe` is not given it and could not
    write there if it wanted to. And nothing at all observed the "reads nothing" half: a probe
    that branched on `env.offline` passed unremarked.

    So: the env is a double that raises on any attribute read, which makes the first half
    observable; and the probe's own body is parsed, which makes the second half structural --
    the only call it may contain is the `ProbeVerdict` it returns. Comments and strings are
    irrelevant here because an `ast.Call` is not a mention (rule 3).
    """
    verdict = FsLocal.probe(_HostileEnv())  # type: ignore[arg-type]
    assert verdict.status is ProbeStatus.OK
    assert verdict.detail

    body = ast.parse(textwrap.dedent(inspect.getsource(FsLocal.probe)))
    called = {
        node.func.attr if isinstance(node.func, ast.Attribute) else getattr(node.func, "id", "?")
        for node in ast.walk(body)
        if isinstance(node, ast.Call)
    }
    assert called == {"ProbeVerdict"}, f"the probe calls out to {sorted(called)}"

    # And a real `ProbeEnv` reaches the same verdict, so the double is not the only input the
    # method accepts.
    env = ProbeEnv(
        platform=sys.platform,
        machine="x86_64",
        python=(3, 11),
        which={},
        gpu_present=False,
        vram_gb=0.0,
        offline=True,
    )
    assert FsLocal.probe(env) == verdict


def test_a_driver_config_list_arrives_as_a_string_and_an_empty_one_keeps_the_default(
    tree: Path,
) -> None:
    """04 section 2.7's `[config]` is a closed JSON-Schema subset over `Scalar` -- no arrays.

    So a glob list arrives comma-separated, and an empty value means "the shipped default" and
    never "match nothing": an `include` of `()` walks a tree and emits nothing, which is
    indistinguishable from an empty corpus.

    **"The shipped default" is asserted as the id set and not as `byte_len > 0`.** A driver that
    fell back to some other glob list -- or, the case that actually shipped unnoticed, to no
    `exclude` list at all -- still emits a non-empty NDJSON body, so the size of the artefact
    proves nothing about which globs were applied. The expected set is written out literally from
    the `tree` fixture: `node_modules/**` excluded by 05:442's default and `.hidden/**` by
    `hidden = false`, with `nodemodules/keep.txt` kept because the pattern names a segment.
    """
    io = FakeIO()
    locator = locator_for(tree)

    default = FsLocal(include="").enumerate(locator, io)
    assert default.produced[0].byte_len > 0
    body = default.produced[0].inline
    assert body is not None
    assert {json.loads(line)["id"] for line in body.decode("utf-8").splitlines()} == {
        "a.txt",
        "a/b.txt",
        "docs/q3.pdf",
        "docs/reports/deep.txt",
        "nodemodules/keep.txt",
        "readme.md",
    }

    narrowed = FsLocal(include="readme.md").enumerate(locator, FakeIO())
    body = narrowed.produced[0].inline
    assert body is not None
    ids = [json.loads(line)["id"] for line in body.decode("utf-8").splitlines()]
    assert ids == ["readme.md"]


@dataclass(eq=False)
class FakeIO:
    """A `DriverIO` stand-in: a blob sink, a ceiling, and a cancel flag.

    `ArtifactRef.of` meters against `max_output_bytes` and keys the meter on the `DriverIO`
    identity, in a `WeakKeyDictionary` -- so this has to be hashable BY IDENTITY, which is why
    it is `eq=False`: a dataclass with the default `__eq__` has no `__hash__` at all. Each call
    that wants its own ceiling gets its own `FakeIO`.
    """

    max_output_bytes: int = 1 << 20
    tmpdir: str = ""
    deadline_ms: int = 30_000
    cancel: bool = False
    blobs: object = None
    puts: list[bytes] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.blobs = self

    def put(self, data: bytes) -> str:
        self.puts.append(data)
        return f"cas://{hashlib.sha256(data).hexdigest()}"

    def cancelled(self) -> bool:
        return self.cancel

    def log(self, event: str, **fields: object) -> None:
        del event, fields

    def progress(self, done: int, total: int | None) -> None:
        del done, total

    def service(self, name: str) -> object:
        raise AssertionError(f"acquire.fs.local attaches no Service ({name})")


# --------------------------------------------------------------------------------------------
# 7. The constants against the plan, and the G17 posture
# --------------------------------------------------------------------------------------------


def test_the_ingest_defaults_are_the_plan_s(plan: object) -> None:
    """`[ingest]`'s shipped values, against 05-ingest-and-routing.md's own TOML fence.

    The plan document is the other side of this comparison, not another copy of the constant --
    which is the difference between pinning a value and pinning agreement. `config.KEYS` carries
    no `[ingest]` table at all, so there is no third home to check against and that gap is
    reported rather than papered over here.
    """
    plan.require()  # type: ignore[attr-defined]
    fences = [
        table
        for table in plan.toml_fences("05-ingest-and-routing.md")  # type: ignore[attr-defined]
        if "ingest" in table
    ]
    assert fences, "05-ingest-and-routing.md has no [ingest] TOML fence"
    ingest = fences[0]["ingest"]
    assert tuple(ingest["include"]) == acquire.DEFAULT_INCLUDE
    assert tuple(ingest["exclude"]) == acquire.DEFAULT_EXCLUDE
    assert ingest["follow_symlinks"] == acquire.DEFAULT_FOLLOW_SYMLINKS
    assert ingest["max_depth"] == acquire.DEFAULT_MAX_DEPTH
    assert ingest["max_unit_bytes"] == acquire.DEFAULT_MAX_UNIT_BYTES
    assert ingest["hidden"] == acquire.DEFAULT_HIDDEN


def test_the_constants_are_the_literals_the_plan_prints() -> None:
    """The same numbers as literals, so the suite still pins them without `_plan/` in the tree.

    `_plan/` is `.gitignore`d (conftest's `PlanDocs.available`), so the previous test skips on a
    clean clone. These are the values it would have asserted.
    """
    assert acquire.DEFAULT_MAX_UNIT_BYTES == 2_147_483_648
    assert acquire.DEFAULT_MAX_DEPTH == 32
    assert acquire.DEFAULT_INCLUDE == ("**/*",)
    assert acquire.DEFAULT_EXCLUDE == (
        "**/.git/**",
        "**/node_modules/**",
        "**/.omniweave/**",
        "**/~$*",
    )
    assert acquire.DEFAULT_HIDDEN is False
    assert acquire.DEFAULT_FOLLOW_SYMLINKS is False
    assert acquire.MAX_UNITS_PER_CALL == 5_000
    assert acquire.PLAN_BATCH == 512
    assert acquire.CONNECTOR == "fs"
    assert acquire.LOCATOR_SCHEME == "file"
    assert acquire.DISCOVERED == "discovered"
    assert acquire.CURSOR_SEP == "\x00"
    assert acquire.TMP_FIRST == "c/000001"
    assert acquire.SCOPE_RULES == ("explicit", "inherited")
    assert tuple(TrustClass) == (TrustClass.INTERNAL, TrustClass.UNTRUSTED_EXTERNAL)


def test_the_state_and_scope_rule_domains_are_the_shipped_ddl_s(migrations: Path) -> None:
    """`unit.state` and `unit.scope_rule` are CHECK-constrained, so the writer's values must fit.

    Read off `0004_runtime.sql` rather than off a transcription: a migration that narrowed either
    domain would otherwise fail at the first `INSERT` of a corpus scan instead of here.
    """
    ddl = (migrations / "0004_runtime.sql").read_text(encoding="utf-8")
    assert f"'{acquire.DISCOVERED}'" in ddl
    for value in acquire.SCOPE_RULES:
        assert f"'{value}'" in ddl
    assert "scope_rule IN ('explicit','inherited') OR scope_rule IS NULL" in ddl


def test_a_bare_import_of_omniweave_core_does_not_load_the_enumerator(
    interpreter: object,
) -> None:
    """G17's posture for this module, asserted rather than assumed.

    The nine LAZY names of 11-repo-layout.md section 1.3 include `store`, and this module imports
    `omniweave_core.store.sqlite` at module scope -- which is safe only while nothing eager
    imports `omniweave_core.acquire`. `omniweave_core/__init__.py` does not, and this is the
    check that keeps it that way: a future `__init__` line importing the enumerator would drag
    `sqlite3` into every `ow hook prompt`.
    """
    loaded = interpreter.modules_after("import omniweave_core")  # type: ignore[attr-defined]
    assert "omniweave_core.acquire" not in loaded
    assert "omniweave_core.store" not in loaded


def test_a_scope_names_at_least_one_root() -> None:
    """`Scope(roots=())` walks nothing, which is never what a caller meant."""
    with pytest.raises(ValueError, match="at least one root"):
        Scope(roots=())


def test_a_scope_carries_the_corpus_member_the_terminology_lock_names() -> None:
    """Two definition sites, and the field set is the union rather than either one alone.

    02-architecture.md:471 prints `Scope(roots, include, exclude)`; `_plan/_notes/terminology.md`
    :763 and 03-document-model.md:2817 both describe *"roots, globs and a corpus"*. The positional
    spelling still constructs and the lock's member is present -- and the divergence is reported.
    """
    positional = Scope(("c:/x",), ("**/*",), ())
    assert positional.roots == ("c:/x",)
    assert positional.corpus is None
    assert "corpus" in Scope.__dataclass_fields__


def test_a_roster_row_refuses_a_scope_rule_outside_the_check() -> None:
    """`unit.scope_rule IN ('explicit','inherited') OR NULL` -- caught here, not at the INSERT."""
    row = _row("c:/x/1.txt")
    assert row.scope_rule is None
    with pytest.raises(ValueError, match="scope_rule"):
        RosterRow(
            unit_uri="c:/x/1.txt",
            cursor=None,
            stat=StatTriple(1, 2, 3),
            trust_class=TrustClass.INTERNAL,
            last_seen_gen=1,
            scope_rule="whatever",
        )
    assert scan.__kwdefaults__["scope_rule"] == "inherited"


def test_the_derived_column_carries_the_labels_and_the_etag(tree: Path) -> None:
    """05:139 (`labels` -> `unit.derived`) and 05:135 (`etag` -> `unit.derived["etag"]`).

    One column, two sources, and the JSON is written with sorted keys so two runs over one
    unchanged tree produce identical bytes.
    """
    locator = locator_for(tree)
    candidate = CandidateRecord(
        tmp="c/000001",
        stable_id="readme.md",
        next_cursor="readme.md\x0099",
        size=6,
        mtime_ns=7,
        etag='W/"abc"',
        labels={"walk_depth": 1},
    )
    row = roster_row_of(locator, candidate, indexed_at_ns=8, last_seen_gen=2)
    assert row.params()["derived"] == '{"etag":"W/\\"abc\\"","walk_depth":1}'
    assert row.cursor == "readme.md\x0099"
    assert row.stat == StatTriple(size=6, mtime_ns=7, indexed_at_ns=8)


# --------------------------------------------------------------------------------------------
# 8. The runner: `tools/ow_discover.py`'s three exit codes
# --------------------------------------------------------------------------------------------


def _discover_main() -> Callable[..., int]:
    """`tools/ow_discover.py`'s `main`, loaded by path.

    `tools/` is not an installed package, so the runner is loaded the way `test_gate_crash.py`
    loads its own subject rather than by an import statement `tools/gate_layers.py` would then
    have to explain.
    """
    root = MODULE.parents[4]
    path = root / "tools" / "ow_discover.py"
    spec = importlib.util.spec_from_file_location("ow_discover_under_test", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.main


def _all_units(path: Path) -> list[dict[str, object]]:
    """Every `unit` row of a store the runner has closed, ordered by uri.

    The runner's whole job is the rows it leaves behind, so a test that reads only its stdout is
    testing the printer. This opens the file the runner was pointed at, after `main` returned.
    """

    def run(connection: sqlite3.Connection) -> list[dict[str, object]]:
        columns = ", ".join(DISCOVERED_COLUMNS)
        return [
            dict(zip(DISCOVERED_COLUMNS, row, strict=True))
            for row in connection.execute(
                f"SELECT {columns} FROM unit ORDER BY unit_uri"  # noqa: S608 - a fixed tuple
            )
        ]

    with ow.StoreThread(lambda: ow.connect(path)) as thread:
        return thread.run(ow.Unit(name="test read", run=run))  # type: ignore[return-value]


def test_the_runner_exits_zero_and_the_rows_it_wrote_carry_its_arguments(
    tmp_path: Path, tree: Path
) -> None:
    """Exit 0, the printed summary, AND the roster rows the store actually holds.

    **The store is the half that was missing.** The previous version of this test read only
    stdout, so three separate defects passed it: a runner that dropped `--generation` and stamped
    `last_seen_gen = 1`; one that dropped `--now-ns` and stamped `indexed_at_ns = 0`; and one that
    wrote NO ROSTER ROWS AT ALL, since the tally is filled by consuming `scan()`'s generator and
    a `write_roster` handed a generator that yields nothing still prints a perfect summary. Its
    docstring claimed "the printed summary is the row the store was given" and nothing read the
    store.

    So the counters are cross-checked against the row count -- two sources, the subject's tally
    and SQLite's `unit` table -- and the two injected values are asserted where they land:
    `--generation 5` in `unit.last_seen_gen`, `--now-ns` in `unit.indexed_at_ns` (02:472's third
    stat member) and in `ingest_scope.scanned_at_ns`.
    """
    store_path = tmp_path / "index.owstore"
    out = io.StringIO()
    code = _discover_main()(
        [
            "--root",
            str(tree),
            "--store",
            str(store_path),
            "--create",
            "--now-ns",
            "1757030400123456789",
            "--generation",
            "5",
            "--json",
        ],
        out=out,
    )
    printed = out.getvalue().splitlines()
    row = json.loads(printed[-1])
    assert code == 0
    assert row["complete"] == 1
    assert row["discovered"] == row["indexed"] + row["skipped"]
    assert row["scanned_at_ns"] == 1757030400123456789
    assert row["scope_id"] == scope_id_for(locator_for(tree))

    units = _all_units(store_path)
    assert len(units) == 6, [unit["unit_uri"] for unit in units]
    assert len(units) == row["indexed"]
    assert {unit["last_seen_gen"] for unit in units} == {5}
    assert {unit["indexed_at_ns"] for unit in units} == {1757030400123456789}
    assert {unit["state"] for unit in units} == {"discovered"}
    assert {unit["connector"] for unit in units} == {"fs"}
    assert {unit["trust_class"] for unit in units} == {"internal"}
    assert all(str(unit["unit_uri"]).startswith(row["scope_id"]) for unit in units)


def test_the_runner_exits_one_when_the_scan_did_not_complete(tmp_path: Path, tree: Path) -> None:
    """Exit 1 is `complete = 0`, and the rows are still written.

    05:371 makes an incomplete scan a recorded fact: the roster rows the truncated call did emit
    are committed, and the coverage row says the scan did not finish so nothing may be marked
    `out_of_scope` from it.

    "Are committed" is read back off the store, because `row["indexed"]` is the tally and the
    tally is filled by the walk rather than by the write -- so the printed `1` is true of a
    runner that wrote nothing.
    """
    store_path = tmp_path / "index.owstore"
    out = io.StringIO()
    code = _discover_main()(
        [
            "--root",
            str(tree),
            "--store",
            str(store_path),
            "--create",
            "--now-ns",
            "1",
            "--max-units",
            "1",
            "--json",
        ],
        out=out,
    )
    row = json.loads(out.getvalue().splitlines()[-1])
    assert code == 1
    assert row["complete"] == 0
    assert row["indexed"] == 1

    units = _all_units(store_path)
    assert len(units) == 1
    assert units[0]["state"] == "discovered"
    assert units[0]["indexed_at_ns"] == 1


def test_the_runner_exits_two_when_it_did_not_run(tmp_path: Path, tree: Path) -> None:
    """Exit 2 is "nothing was written", and it is distinguished from exit 1 for a human.

    Two ways in: a root that is not a directory, and a store that does not exist without
    `--create`. Both must leave no store behind.
    """
    main = _discover_main()
    missing_store = tmp_path / "absent.owstore"

    out = io.StringIO()
    assert main(["--root", str(tmp_path / "nope"), "--store", str(missing_store)], out=out) == 2
    assert "DID NOT RUN" in out.getvalue()
    assert not missing_store.exists()

    out = io.StringIO()
    assert main(["--root", str(tree), "--store", str(missing_store)], out=out) == 2
    assert "--create" in out.getvalue()
    assert not missing_store.exists()
