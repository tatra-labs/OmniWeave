"""The `omniweave` distribution's fixtures: one re-export, a reason it is a re-export, and the
two fixtures this distribution owns.

`packages/omniweave-core/tests/conftest.py` is this repository's one reader over `_plan/`. It
builds `PlanDocs` from the workspace root, skips the tests that need it when `_plan/` is absent
(the design tree is `.gitignore`d, so a clean clone has none), and carries the `fences`, `grep`
and `lines` helpers every transcription test in the tree is written against.

`repo_root` and `migrations` come across for the same reason and with the same force. `migrations`
in particular is not a path a test may compose: the migration set is `omniweave-core` package data
rather than a root directory (`_plan/_notes/build-defects.md` D12), so a second spelling here would
be a second answer to where the DDL lives.

Re-exported rather than re-declared. A second `PlanDocs` here would be a second answer to "where
is the plan and what counts as a document" -- `_notes/.snapshots/` is excluded from `documents()`
for a reason, and a copy that forgot would assert against a superseded draft and pass. INV-21 is
about facts, and "the plan is at `<root>/_plan`" is one.

The `sys.path` insertion is what makes the import work at all: pytest puts each `conftest.py`'s own
directory on the path, so `omniweave-core`'s is importable as a top-level `conftest` only from
inside that package's tests. Naming the directory here is the cost of two distributions sharing
one fixture without a test-support package neither of them ships.

`released_catalog` is this distribution's own: the shipped catalog with the office driver as a
released build carries it, the one catalog under which `resolve()` grants seam S1. Two test modules
drive S1, one through `pipeline.inproc_host` and one through a whole `ow ingest`, and a copy in
each would be two answers to what "released" means.

`git_index` is the other: a git index built byte by byte from git's `index-format.txt`. Both
`test_doctor_gitindex.py` and `test_doctor.py` write indexes, and the format should have one
spelling in the test tree, as it has one in `omniweave.doctor.gitindex` (W7.8c).
"""

from __future__ import annotations

import dataclasses
import importlib.util
import struct
import sys
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

_CORE_CONFTEST = Path(__file__).resolve().parents[2] / "omniweave-core" / "tests" / "conftest.py"
_MODULE = "omniweave_core_tests_conftest"

if _MODULE not in sys.modules:
    _spec = importlib.util.spec_from_file_location(_MODULE, _CORE_CONFTEST)
    assert _spec is not None and _spec.loader is not None
    _loaded = importlib.util.module_from_spec(_spec)
    sys.modules[_MODULE] = _loaded
    _spec.loader.exec_module(_loaded)

PlanDocs = sys.modules[_MODULE].PlanDocs
migrations = sys.modules[_MODULE].migrations
plan = sys.modules[_MODULE].plan
repo_root = sys.modules[_MODULE].repo_root

__all__ = [
    "GitIndex",
    "PlanDocs",
    "git_index",
    "migrations",
    "plan",
    "released_catalog",
    "repo_root",
]

OFFICE = "parse.office.anydoc"


@pytest.fixture
def released_catalog() -> object:
    """The shipped catalog with `parse.office.anydoc` as a RELEASED build would carry it.

    Two facts move, and they are the two DR9 conjuncts a checkout cannot meet: the trust tier a
    wheel install is pinned at (`first_party`; an editable install is `unpinned`, D576), and a
    green `fuzz` suite in `[quality.suites]`, which only `ow conform` writes and no shipped card
    carries (D599). Every other conjunct is the card's own, so `resolve()` -- not a test -- is
    what grants `inproc` under it.
    """
    from omniweave_core.discovery import catalog  # noqa: PLC0415
    from omniweave_core.drivers.catalog import Catalog  # noqa: PLC0415
    from omniweave_ports.types import TrustTier  # noqa: PLC0415

    shipped = catalog()
    card = shipped.cards[OFFICE]
    released = dataclasses.replace(
        card, quality=dataclasses.replace(card.quality, suites={"fuzz": "pass"})
    )
    return Catalog.assemble(
        validity_key=shipped.validity_key,
        cards={**shipped.cards, OFFICE: released},
        probe_status={key: str(value) for key, value in shipped.probe_status.items()},
        trust={**shipped.trust, OFFICE: TrustTier.FIRST_PARTY},
        tombstones=shipped.tombstones.values(),
    )


class GitIndex:
    """git's index format, written: the inverse of `omniweave.doctor.gitindex.parse_index`."""

    REGULAR = 0o100644
    DIRECTORY = 0o040000

    @staticmethod
    def varint(value: int) -> bytes:
        """git's `encode_varint` (`varint.c`): each continuation byte stands for one more."""
        out = [value & 0x7F]
        value >>= 7
        while value:
            value -= 1
            out.append(0x80 | (value & 0x7F))
            value >>= 7
        return bytes(reversed(out))

    @classmethod
    def entry(
        cls,
        path: bytes,
        *,
        version: int,
        previous: bytes = b"",
        hash_bytes: int = 20,
        extended: bool = False,
        mode: int = REGULAR,
    ) -> bytes:
        """One entry: stat data, object id, flags, the extended word if set, then the path."""
        stat = struct.pack(">10I", 0, 0, 0, 0, 0, 0, mode, 0, 0, 0)
        flags = min(len(path), 0xFFF) | (0x4000 if extended else 0)
        head = stat + b"\x11" * hash_bytes + struct.pack(">H", flags)
        if extended:
            head += struct.pack(">H", 0x2000)  # intent-to-add, the flag `git add -N` sets
        if version == 4:
            common = 0
            while common < min(len(path), len(previous)) and path[common] == previous[common]:
                common += 1
            return head + cls.varint(len(previous) - common) + path[common:] + b"\0"
        body = head + path
        return body + b"\0" * (8 - len(body) % 8)

    @classmethod
    def build(
        cls,
        paths: Sequence[bytes],
        *,
        version: int = 2,
        hash_bytes: int = 20,
        extended: frozenset[bytes] = frozenset(),
        modes: Mapping[bytes, int] | None = None,
        extensions: bytes = b"",
    ) -> bytes:
        """A whole index: header, `paths` in order, `extensions` verbatim, a zero checksum."""
        out = b"DIRC" + struct.pack(">II", version, len(paths))
        previous = b""
        for path in paths:
            out += cls.entry(
                path,
                version=version,
                previous=previous,
                hash_bytes=hash_bytes,
                extended=path in extended,
                mode=(modes or {}).get(path, cls.REGULAR),
            )
            previous = path
        return out + extensions + b"\0" * hash_bytes


@pytest.fixture
def git_index() -> type[GitIndex]:
    """The index writer, as a fixture because a test module cannot import a sibling (TID252)."""
    return GitIndex
