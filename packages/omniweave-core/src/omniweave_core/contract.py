"""The contract stamp: the four module constants a third party pins, and nothing else.

This module is the **sole code home** of two of omniweave's three version axes — `CONTRACT`, the
driver/target ABI, and `SCHEMA`/`SCHEMA_MINOR`, the L2-model-and-store-schema pair — and the one
site in the framework that formats `f"{SCHEMA}.{SCHEMA_MINOR}"`. Settled by
`adr/0009-schema-single-home.md` against charter erratum E72; stated identically in
11-repo-layout.md section 4.1, 07-store-and-retrieval.md section 3.1 and 03-document-model.md
section 15.1.

It holds constants. **Deciding what the contract contains is not its job** and neither is holding a
file's value: the disk home of `SCHEMA` is `index_state.schema`, one row, written `<major>.<minor>`
as a string, and `meta` never gains a `schema` key (07-store-and-retrieval.md section 3.8).

Its counterpart ruling: `omniweave_core.limits` carries no version constant, now or ever, and
`SCHEMAS_SUPPORTED` is not added — 07-store-and-retrieval.md section 3.1's four-row compatibility
table is already a total function of (file major, file minor, reader major, reader minor), so a
supported-set would restate what the table computes (ADR-9, alternatives rejected).

Tier T-CONTRACT: a third party pins these and builds against them. `CONTRACT` moves only on a
`RELEASE` MINOR, announced and migration-guided, and G16 loads the previous two releases'
conformance-template drivers against HEAD (02-architecture.md section 2 row 2).

Specified in 02-architecture.md section 2 row 2 and 18-api-sketch.md section 1.1.
"""

from __future__ import annotations

from importlib.metadata import PackageNotFoundError as _NotFound
from importlib.metadata import version as _dist_version

__all__ = [
    "CONTRACT",
    "CONTRACTS_SUPPORTED",
    "RELEASE",
    "SCHEMA",
    "SCHEMA_MINOR",
    "SCHEMA_STRING",
]


def _release() -> str:
    """Read `RELEASE` from the installed distribution's own metadata rather than re-declaring it.

    11-repo-layout.md section 4.2 enumerates **forty** version-bearing sites across eighteen files
    and `packages/omniweave-core/pyproject.toml`'s `[project] version` is the one that carries
    `RELEASE` for this distribution; a literal here would be a forty-first that
    `tools/check_versions.py` does not know about, which is INV-21's "a second home for one fact"
    exactly. `importlib.metadata` is stdlib, so D1 holds.

    The fallback is deliberately not a semver: an uninstalled source tree has no `RELEASE`, and a
    plausible-looking placeholder would be worse than an obviously wrong one.
    """
    try:
        return _dist_version("omniweave-core")
    except _NotFound:  # pragma: no cover - only on an uninstalled source tree
        return "0+unknown"


RELEASE: str = _release()
"""The one semver every first-party distribution carries — `"0.1.0"` at release 1.

`omniweave-ports` is the single exception: it is versioned by **Port major** (`1.0.0` at release 1)
because a driver pins it, and a driver that pinned `RELEASE` would have pinned the framework
(11-repo-layout.md section 4.1). `ow --version` prints this beside `CONTRACT` and `SCHEMA`.

Read from distribution metadata, never declared here — see `_release()`.
Printed in 18-api-sketch.md section 1.1.
"""

CONTRACT: int = 1
"""The driver/target ABI a third party pins — the only version a third party pins at all.

Moves on a `RELEASE` **MINOR**, announced and migration-guided, and never on a PATCH. What moves it:
removing or renaming anything in `omniweave_ports`, changing a Port protocol's signature, requiring
a new card key, changing a wire frame's meaning, or narrowing an accepted `card_schema`. What does
not: adding a Port protocol, adding an optional key inside `[capability.<port>]`, adding a
`FailureClass` member, a new `RejectCode` row in `codes.toml` (11-repo-layout.md section 4.3).

P1 ends at `CONTRACT = 1` and `card_schema = 1` (16-roadmap.md section 1).
"""

CONTRACTS_SUPPORTED: frozenset[int] = frozenset({1})
"""Every `CONTRACT` major this build accepts a driver against.

A driver never reads `CONTRACT` from a dependency bound. It declares what it supports on its card
and `activate()` checks that declaration against this set (04-driver-system.md section 5.3,
11-repo-layout.md section 4.1). Port 1 drivers keep resolving until the framework drops their major
from here, which is what makes a Port 2 a new distribution version rather than a break
(11-repo-layout.md section 4.1's Port-major row).

`CONTRACT in CONTRACTS_SUPPORTED` always holds: a build that cannot accept its own ABI is
incoherent.
"""

SCHEMA: int = 1
"""The **major** of the pair versioning the L2 model and the store schema together.

A major is a published read-contract break over the `[SOR]` set of 03-document-model.md section 13.1
and carries a two-release deprecation window (charter section 6.6). A file whose major is ahead of
this one is refused at open with `OW-S-030` / `OW_SCHEMA_AHEAD`; a file behind it migrates forward
on an exclusive write open (07-store-and-retrieval.md section 3.1).

This is a **stamp**, not a ceiling, which is why it lives here and not in `omniweave_core.limits`
(ADR-9 decision 1; 02-architecture.md section 2 rows 2 and 7).
"""

SCHEMA_MINOR: int = 0
"""The **minor** of that pair, reset to `0` at a major bump.

It exists because two of the four rows of 07-store-and-retrieval.md section 3.1's compatibility
table compare a file's minor against the **reader's** minor — equal-major/file-minor-ahead serves
reads and refuses writes, equal-major/file-minor-behind migrates forward on additive DDL — and
naming a code home for the major while leaving the reader's minor homeless would have discharged
`11#OQ-9` and reproduced its defect one field over (ADR-9 decision 2).
"""

SCHEMA_STRING: str = f"{SCHEMA}.{SCHEMA_MINOR}"
"""`<major>.<minor>` — **the one site in the framework that formats the pair.**

Two consumers, and neither re-derives it: `index_state.schema` holds this string as its single row
(07-store-and-retrieval.md section 3.8), and `ow --version` prints `SCHEMA` in this form beside
`RELEASE` and `CONTRACT` (11-repo-layout.md section 2). `G27(b)` asserts, at the **end** of the
`0001` -> `0005` migration run on `MIN_SQLITE`, that `index_state` holds exactly one `schema` row
equal to this value and that `meta` holds no `schema` key (store property ST24).

ADR-9 decision 2 requires "exactly one site" and prints the f-string but coins no name for it; the
name is this module's. A module constant rather than a function because the pair is fixed at build
time and a function would invite a second call site to reformat it.
"""
