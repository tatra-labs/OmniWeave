"""Seam S2's register: the reader for `tools/toolchains.toml`, and nothing that spawns.

A **Toolchain** is a digest-pinned non-Python execution bundle invoked as a one-shot child over
`omniweave-target/1`. TypeScript exists in this framework for exactly two of them -- `deck` and
`video` -- and for nothing else, because only those two OUT targets need a browser-grade layout
engine (11-repo-layout.md section 3.1). This module is the Python half's entry point, and at W1.6
it is **the manifest reader only**: `ToolchainSpec`, `NodeRuntime`, the two-table grammar and its
validation. Node resolution, the full-sha256 verification of a downloaded bundle, the spawn and the
SIGTERM -> SIGKILL + 5 s process-group reap are `run(spec, job_dir, *, timeout_s, ctx)`'s
(02-architecture.md section 2 row 16), which D810 adds below, and with it this module's
`subprocess`: one of the two homes G8's rule gives it.

**It NEVER reads the network.** The register's whole purpose is that the digest is in-tree and in
the wheel: "if the digest were fetched alongside the bundle, verifying it would prove only that the
bundle matches itself" (11-repo-layout.md section 1.7's *Extends the charter* note). A reader that
could fetch would defeat the file it reads.

**Two tables because the app is ours and the runtime is not** (section 3.2). The app bundle is
platform-independent -- one `dist/render.mjs`, one sha256, one `[[toolchain]]` row -- because
esbuild emits one file and the bundle carries no binary. Node is not ours and omniweave never
repackages it, so each `[[node]]` row records a version, a platform tag and a sha256 **transcribed
from nodejs.org's own `SHASUMS256.txt` at pin time**. Keeping them apart is what stops a platform
matrix appearing in a framework that publishes only `py3-none-any` wheels.

LAZY. `toolchain` is one of the nine names G17 asserts a bare `import omniweave_core` does not
load, because `ow hook prompt` has a 250 ms warm p95 budget and pays for every module that import
touches (11-repo-layout.md section 1.3). Nothing eager may import this module.

Specified in 11-repo-layout.md section 3.2 (the manifest, printed) and section 1.7 (why it is
in-tree), 02-architecture.md section 2 row 16 and glossary.md (`ToolchainSpec`).

## Rulings (D810): `run()`

1. **One request, one fresh child.** `run(spec, job_dir, *, timeout_s, ctx, verb, request)`
   resolves node, verifies the bundle, spawns, exchanges one request and reaps. A Toolchain is
   a one-shot child (glossary.md), so nothing is kept between calls.
2. **The node ladder is section 3.2's.** It tries `$OMNIWEAVE_NODE` as named, then each
   register row for this platform whose version the range accepts, installed at
   `$OMNIWEAVE_HOME/node/<version>-<platform>/bin/node[.exe]`, and then `node` on `PATH` if
   `node --version` satisfies the range. On Windows only `node.exe` is ever looked for, never
   a `.cmd` shim. With no rung, the result is `CapabilityMissing`, exit 64, naming
   `ow targets install <name>`: the target is pruned, never an `ImportError`.
3. **The digest is in the path and checked on every invocation.** The install directory is
   `$OMNIWEAVE_HOME/toolchains/<name>@<version>-<sha256>/` (02 section 2), holding the
   verified archive, `bundle.tar.gz`. `run()` hashes the whole archive against the register's
   full sha256, then writes its `entry` member to `ctx.scratch` and runs those bytes. Running
   what was just verified, rather than an extracted copy, leaves nothing to swap between
   check and use. A mismatch is `OW_TARGET_TOOLCHAIN_DIGEST` and never fetches; a missing
   archive is `CapabilityMissing`.
4. **`cwd` is the JobDir, and the environment is constructed.** The child gets only
   `ENV_ALLOWLIST`'s variables the host has (the OS's own and the temp directory), so no
   token, proxy or `NODE_OPTIONS` reaches it. On Windows it is born suspended in a job
   object, as an S4 worker is (D636); on POSIX it leads a new session.
5. **stdout is control and stderr is a log.** Each stdout line must be one JSON object, under
   1 MiB in all; anything else ends the call. stderr is drained into a bounded ring, kept for
   the result and never parsed.
6. **The frames.** The host sends `hello` (`proto`, `verb`). The child answers `ready`,
   naming the spec's toolchain and version. The host sends the request (`t` = the verb, plus
   its fields), the child sends `progress`* (`done`, `total`) and one `result` whose `status`
   is `ok` or `blocked`, the host sends `bye`, and the child exits. A `compile` exits 0 iff it
   wrote `out/receipt.json`; another verb answered `ok` exits 0. A child exiting 64, even
   before its `ready`, has no runtime of its own: `CapabilityMissing`. Every other break is
   `OW_TARGET_TOOLCHAIN_FAILED`.
   `blocked` is a frame outcome, not a gate: the framework computes `GateStatus` itself
   (09 section 12.2).
7. **One deadline, from `ctx.clock`.** `timeout_s` bounds the whole exchange, the exit
   included. Past it, or on any break, the child is reaped: on POSIX SIGTERM to its group,
   then SIGKILL at +5 s; on Windows the job object terminates the tree.
"""

from __future__ import annotations

import contextlib
import hashlib
import io
import json
import os
import queue
import re
import shutil
import signal
import subprocess
import sys
import tarfile
import threading
import tomllib
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, Final, Literal

from omniweave_core.errors import CapabilityMissing, ConfigError, TargetError
from omniweave_core.host.subproc import CREATE_SUSPENDED, JobObject, StderrRing

if TYPE_CHECKING:
    from omniweave_core.clock import Clock

__all__ = [
    "BUNDLE_FILE",
    "ENV_ALLOWLIST",
    "MANIFEST_NAME",
    "NODE_KEYS",
    "NODE_PLATFORMS",
    "PROTOCOL",
    "RANGE_OPERATORS",
    "RECEIPT",
    "STDOUT_MAX_BYTES",
    "TOOLCHAIN_KEYS",
    "TOOLCHAIN_MANIFEST_SCHEMAS",
    "VERBS",
    "NodeRange",
    "NodeRuntime",
    "ToolchainContext",
    "ToolchainManifest",
    "ToolchainResult",
    "ToolchainSpec",
    "VersionClause",
    "install_dir",
    "parse_manifest",
    "read_manifest",
    "resolve_node",
    "run",
]


# --------------------------------------------------------------------------------------------
# 1. The grammar, as constants. Every closed set here is one the plan prints or prices.
# --------------------------------------------------------------------------------------------

MANIFEST_NAME: Final[str] = "toolchains.toml"
"""The register's file name. It lives at `tools/toolchains.toml` and is read from there.

`tools/` is the directory 11-repo-layout.md section 1.7 puts it in, alongside `layers.toml`,
`weights.toml` and `licences.toml`; the path is not hardcoded here because the reader takes a
`Path`, and a repo-root walk belongs to whichever caller already knows where the checkout is.
"""

TOOLCHAIN_MANIFEST_SCHEMAS: Final[frozenset[int]] = frozenset({1})
"""Every top-level `schema` this build reads. Section 3.2's manifest opens with `schema = 1`.

A register from a newer grammar is refused with the upgrade as the fix, never silently half-read:
the file's whole job is to pin a digest, and a row this build cannot fully parse is a digest it
cannot fully check. Same asymmetry as `card_schema` (04-driver-system.md section 5.3).
"""

TOOLCHAIN_KEYS: Final[frozenset[str]] = frozenset(
    {"name", "version", "entry", "node_range", "bundle_sha256", "bundle_url"}
)
"""The six keys of a `[[toolchain]]` row, transcribed from section 3.2's printed manifest.

All six are REQUIRED and an unknown key is a hard error. `tools/` files are "either append-only
against the previous tag or generated from a declaration site, and none of them may be edited to
make a gate pass" (section 1.7) -- a register that tolerated an unknown key would let a typo'd
`bundle_sha_256` read as "no digest declared", which is the one failure this file exists to
prevent.
"""

NODE_KEYS: Final[frozenset[str]] = frozenset({"version", "platform", "sha256", "url"})
"""The four keys of a `[[node]]` row, transcribed from section 3.2's printed manifest.

There is no `entry` and no range: a `[[node]]` row is a download to verify, not a program to run.
`ow doctor --runtime` re-verifies an installed node against its row and reports a mismatch as
`TOOLCHAIN_DIGEST` **on the runtime** rather than on the bundle -- two digests, two messages.
"""

NODE_PLATFORMS: Final[tuple[str, ...]] = (
    "darwin-arm64",
    "darwin-x64",
    "linux-arm64",
    "linux-x64",
    "win-arm64",
    "win-x64",
)
"""The platform tags a `[[node]]` row may carry.

**Derived, not printed, and worth a second reader.** Section 3.2 prints exactly one tag
(`linux-x64`) and then prices the alternative: vendoring Node as platform-tagged wheels was
rejected because it "multiplies the release matrix by six", where "recording six upstream digests
costs six lines and multiplies nothing". Six rows means six platforms, and the six tags themselves
are nodejs.org's own asset names for a modern release -- `node-v<version>-<tag>.tar.xz`, plus
`.zip` on Windows. `linux-armv7l` and `linux-ppc64le` exist upstream and are deliberately not here:
a seventh tag would be a seventh row and contradict the six the charter's pricing settled on.

Sorted, so the constant reads as a set rather than as a priority order. Nothing ranks these.
"""

RANGE_OPERATORS: Final[tuple[str, ...]] = (">=", "<=", "==", "!=", ">", "<")
"""The comparison operators a `node_range` clause may use, longest spelling first.

**Derived from the one range the plan prints**, `">=20.11,<23"`: comma-separated clauses, each an
operator followed by a dotted version. npm's semver dialect (`^`, `~`, `||`, `x` wildcards,
hyphen ranges) is deliberately NOT implemented -- none of it appears anywhere in the plan, and a
range grammar this reader accepts but `run()` misreads would resolve a Node the bundle was never
built against. Anything outside this grammar is refused at read time, where a human is looking.

Longest-first is load-bearing: `>=` must be tried before `>`, or `>=20.11` parses as `>` applied to
`=20.11` and the version parse fails with the wrong message.
"""

_NAME_RE: Final = re.compile(r"\A[a-z][a-z0-9_]{0,31}\Z")
"""A Toolchain name: `deck`, `video`. It is a directory name under `toolchains/` and the suffix of
`io.service("toolchain:<name>")` (09-generation.md section 12.2), so it must be a bare identifier.

The grammar is not printed and is filled here; the **roster** deliberately is not. `tools/
check_versions.py` already asserts that this register carries exactly two rows, `deck` and `video`,
and a second copy of that fact here would be INV-21's second home for it.
"""

_VERSION_RE: Final = re.compile(r"\A(0|[1-9][0-9]*)(\.(0|[1-9][0-9]*)){0,2}\Z")
"""One to three dot-separated integers, no leading zeros: `20`, `20.11`, `20.18.1`, `0.4.2`.

Both printed versions fit (`"0.4.2"`, `"20.18.1"`) and so does the range's `20.11`. Pre-release and
build metadata are refused: a Node release-candidate is not a thing `ow targets install` fetches,
and `[[toolchain]] version` is checked against `RELEASE` by `tools/check_versions.py`, which is a
plain semver.
"""

_SHA256_RE: Final = re.compile(r"\Asha256:[0-9a-f]{64}\Z")
"""`sha256:` plus **sixty-four** lowercase hex.

"The digest is the *full* sha256, not a 16-hex prefix. 64 bits is weak against intent" (section
3.2). The length check is that sentence, mechanised: a truncated digest is refused at read time
rather than compared against a truncation of the real one.
"""

_URL_SCHEME: Final[str] = "https://"
"""The only scheme a `bundle_url` or a `[[node]] url` may carry.

`$OMNIWEAVE_HOME/toolchains/` is a user-writable directory holding executable code and the digest
is the only thing between a compromised home directory and arbitrary execution. Refusing `http://`
and `file://` in the register costs nothing -- both printed URLs are `https` -- and removes the
one shape where a register edit alone redirects an install. Not printed in the plan; recorded here
as a filled silence.
"""


# --------------------------------------------------------------------------------------------
# 2. Node version ranges.
# --------------------------------------------------------------------------------------------


def _version_tuple(text: str, where: str, source: str) -> tuple[int, ...]:
    """`"20.11"` -> `(20, 11)`, or a `ConfigError` naming the row and the key."""
    if _VERSION_RE.fullmatch(text) is None:
        raise _invalid(source, f"{where} is {text!r}, not one to three dotted integers")
    return tuple(int(part) for part in text.split("."))


def _padded(left: tuple[int, ...], right: tuple[int, ...]) -> tuple[tuple[int, ...], ...]:
    """Both tuples zero-extended to the same length, so `20.11` and `20.11.0` compare equal.

    Comparing `(20, 11)` against `(20, 11, 0)` directly makes the shorter one the smaller, which
    would make `>=20.11` reject Node 20.11.0 -- the exact version the range was written to admit.
    """
    width = max(len(left), len(right))
    return (
        left + (0,) * (width - len(left)),
        right + (0,) * (width - len(right)),
    )


@dataclass(frozen=True, slots=True)
class VersionClause:
    """One `<operator><version>` of a `node_range`, e.g. `>=20.11`."""

    operator: str
    version: tuple[int, ...]

    def accepts(self, candidate: tuple[int, ...]) -> bool:
        """Whether `candidate` satisfies this clause, both sides zero-padded to equal width."""
        left, right = _padded(candidate, self.version)
        if self.operator == ">=":
            return left >= right
        if self.operator == "<=":
            return left <= right
        if self.operator == "==":
            return left == right
        if self.operator == "!=":
            return left != right
        if self.operator == ">":
            return left > right
        return left < right  # "<" -- the only member of RANGE_OPERATORS left


@dataclass(frozen=True, slots=True)
class NodeRange:
    """A parsed `node_range`: the text as written, and the clauses it means.

    The text is kept because it is what an error message and `ow doctor` print -- a user who wrote
    `">=20.11,<23"` should not be shown a normalised re-rendering of it. The clauses are kept
    because re-parsing per spawn would put a parser on the invocation path.

    A range is a **conjunction**: every clause must hold. Disjunction (`||`) is not in the grammar,
    for the reason `RANGE_OPERATORS` gives.
    """

    text: str
    clauses: tuple[VersionClause, ...]

    def accepts(self, version: str) -> bool:
        """Whether a Node `version` string satisfies every clause.

        This is the predicate step 1 of section 3.2's node ladder applies to `node` on `PATH`:
        `$OMNIWEAVE_NODE`, then `$OMNIWEAVE_HOME/node/<version>-<platform>/bin/node[.exe]`, then
        `node` on `PATH` **if it satisfies `spec.node_range`**, then none -- at which point the
        target is pruned from the plan with a report naming `ow targets install <name>`, never an
        `ImportError`. Resolving the ladder is `run()`'s; this is the one rung it needs from here.

        A version this reader cannot parse is `False` rather than an exception: the input is
        whatever `node --version` printed, and an unrecognisable answer from an unknown binary is a
        reason not to use it, not a reason to fail the run.
        """
        text = version.removeprefix("v")
        if _VERSION_RE.fullmatch(text) is None:
            return False
        candidate = tuple(int(part) for part in text.split("."))
        return all(clause.accepts(candidate) for clause in self.clauses)


def _parse_range(text: str, where: str, source: str) -> NodeRange:
    """`">=20.11,<23"` -> a `NodeRange`, or a `ConfigError` naming the row and the clause."""
    parts = [part.strip() for part in text.split(",")]
    if not text.strip() or any(not part for part in parts):
        raise _invalid(source, f"{where} is {text!r}; a node_range is one or more '<op><version>'")
    clauses: list[VersionClause] = []
    for part in parts:
        operator = next((op for op in RANGE_OPERATORS if part.startswith(op)), None)
        if operator is None:
            raise _invalid(
                source,
                f"{where} clause {part!r} has no comparison operator; "
                f"one of {' '.join(RANGE_OPERATORS)} is required",
            )
        clauses.append(
            VersionClause(
                operator=operator,
                version=_version_tuple(part[len(operator) :].strip(), f"{where} {part!r}", source),
            )
        )
    return NodeRange(text=text, clauses=tuple(clauses))


# --------------------------------------------------------------------------------------------
# 3. The two row types and the manifest.
# --------------------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ToolchainSpec:
    """One `[[toolchain]]` row: a Toolchain's identity.

    "Name, version, the **full** sha256 (a 16-hex prefix is 64 bits and weak against intent), the
    entry argv, and a Node version range" (glossary.md, `ToolchainSpec`). `entry` here is the single
    relative path section 3.2's manifest prints (`"dist/render.mjs"`) rather than a list; the
    glossary's "entry argv" is the argv `run()` builds around it, and the tension between the two
    wordings is recorded rather than resolved by inventing a list-valued key.

    `bundle_url` is where `ow targets install` fetches from, and it is **not** where the digest
    comes from: `bundle_sha256` is in-tree and in the wheel precisely so verification proves more
    than that the bundle matches itself.
    """

    name: str
    version: str
    entry: str
    node_range: NodeRange
    bundle_sha256: str
    bundle_url: str


@dataclass(frozen=True, slots=True)
class NodeRuntime:
    """One `[[node]]` row: a Node runtime omniweave downloads, verifies and never builds.

    `sha256` is **transcribed from nodejs.org's own `SHASUMS256.txt` at pin time**, not computed
    here, which is why `ow doctor --runtime` re-verifies an installed node against this row and
    reports a mismatch on the runtime rather than on the bundle.
    """

    version: str
    platform: str
    sha256: str
    url: str


@dataclass(frozen=True, slots=True)
class ToolchainManifest:
    """The whole of `tools/toolchains.toml`, parsed and validated.

    Two lookups and no ranking. Which Toolchain is wanted comes from the target being compiled and
    which Node is wanted comes from the host's platform tag; neither is a choice this file makes.
    """

    schema: int
    source: str
    toolchains: tuple[ToolchainSpec, ...]
    nodes: tuple[NodeRuntime, ...]

    def toolchain(self, name: str) -> ToolchainSpec | None:
        """The row for `name`, or `None`. Names are unique -- `parse_manifest` refuses a repeat."""
        return next((row for row in self.toolchains if row.name == name), None)

    def node(self, version: str, platform: str) -> NodeRuntime | None:
        """The row for `(version, platform)`, or `None`. The pair is unique in a valid manifest."""
        return next(
            (row for row in self.nodes if row.version == version and row.platform == platform),
            None,
        )

    def nodes_for(self, platform: str) -> tuple[NodeRuntime, ...]:
        """Every runtime row for one platform tag, in declaration order.

        Declaration order and not sorted by version: the register is hand-written and append-only,
        so its order is a fact somebody chose, and a reader that re-sorted would quietly disagree
        with the file a reviewer is reading.
        """
        return tuple(row for row in self.nodes if row.platform == platform)


# --------------------------------------------------------------------------------------------
# 4. The reader.
# --------------------------------------------------------------------------------------------


def _invalid(source: str, detail: str) -> ConfigError:
    """The one refusal shape: what is wrong, where, and the command that clears it.

    `ConfigError`'s class-default symbol is used because the plan binds no `codes.toml` row to a
    malformed Toolchain register -- the same choice `omniweave_core.errors.register_path()` makes
    for an unreadable `codes.toml`, which is the same class of in-tree register. Reported as a gap:
    if `ow targets` gains a `--check`, these refusals want an `OW-T-*` row of their own.
    """
    return ConfigError(
        f"{source}: {detail}",
        fix=f"fix {source}; every [[toolchain]] and [[node]] row is hand-written and reviewed",
    )


def _rows(document: dict[str, object], table: str, source: str) -> list[dict[str, object]]:
    """The `[[<table>]]` array of tables, or `[]`, refusing anything that is not one."""
    raw = document.get(table, [])
    if not isinstance(raw, list):
        raise _invalid(source, f"[[{table}]] is not an array of tables")
    for index, row in enumerate(raw):
        if not isinstance(row, dict):
            raise _invalid(source, f"[[{table}]][{index}] is not a table")
    return list(raw)


def _string(row: dict[str, object], key: str, where: str, source: str) -> str:
    """A required string-valued key, refusing an absent one and a non-string one separately."""
    if key not in row:
        raise _invalid(source, f"{where} is missing the required key {key!r}")
    value = row[key]
    if not isinstance(value, str) or not value:
        raise _invalid(source, f"{where} {key} is not a non-empty string")
    return value


def _known_keys(row: dict[str, object], allowed: frozenset[str], where: str, source: str) -> None:
    """Refuse an unknown key. See `TOOLCHAIN_KEYS` for why this is an error and not a warning."""
    unknown = sorted(set(row) - allowed)
    if unknown:
        raise _invalid(source, f"{where} carries unknown key(s) {', '.join(unknown)}")


def _digest(row: dict[str, object], key: str, where: str, source: str) -> str:
    """A `sha256:<64 hex>` value, refusing a truncated or bare-hex one."""
    value = _string(row, key, where, source)
    if _SHA256_RE.fullmatch(value) is None:
        raise _invalid(source, f"{where} {key} is {value!r}, not 'sha256:' plus 64 lowercase hex")
    return value


def _url(row: dict[str, object], key: str, where: str, source: str) -> str:
    """An `https://` URL. See `_URL_SCHEME`."""
    value = _string(row, key, where, source)
    if not value.startswith(_URL_SCHEME):
        raise _invalid(source, f"{where} {key} is {value!r}; only {_URL_SCHEME} is accepted")
    return value


def _entry(row: dict[str, object], where: str, source: str) -> str:
    """A bundle-relative POSIX path, refusing absolute, backslashed and escaping ones.

    The entry is joined onto a digest-pinned install root and handed to `node`. A `..` component or
    a leading `/` would name a file outside the verified bundle, which is the digest being checked
    and then not used. Windows invokes `node.exe` against this entry **directly, never a `.cmd` or
    `.bat` shim** (section 3.2, codegraph's recorded `EINVAL` scar), so a backslash here would be a
    path the ladder cannot resolve on the platform it exists for.

    A control character is refused too, and it is not a hypothetical: TOML's `"dist\render.mjs"`
    decodes `\r` to a carriage return, so the one spelling an author is most likely to type on
    Windows arrives as a path with a CR in the middle of it rather than as a backslash.
    """
    value = _string(row, "entry", where, source)
    parts = value.split("/")
    if (
        value.startswith("/")
        or "\\" in value
        or any(character < " " or character == "" for character in value)
        or any(part in {"", ".", ".."} for part in parts)
    ):
        raise _invalid(
            source, f"{where} entry is {value!r}; a bundle-relative POSIX path is wanted"
        )
    return value


def _toolchain(row: dict[str, object], index: int, source: str) -> ToolchainSpec:
    """One validated `[[toolchain]]` row."""
    where = f"[[toolchain]][{index}]"
    _known_keys(row, TOOLCHAIN_KEYS, where, source)
    name = _string(row, "name", where, source)
    if _NAME_RE.fullmatch(name) is None:
        raise _invalid(source, f"{where} name is {name!r}, not a lower-case bare identifier")
    version = _string(row, "version", where, source)
    _version_tuple(version, f"{where} version", source)
    return ToolchainSpec(
        name=name,
        version=version,
        entry=_entry(row, where, source),
        node_range=_parse_range(
            _string(row, "node_range", where, source), f"{where} node_range", source
        ),
        bundle_sha256=_digest(row, "bundle_sha256", where, source),
        bundle_url=_url(row, "bundle_url", where, source),
    )


def _node(row: dict[str, object], index: int, source: str) -> NodeRuntime:
    """One validated `[[node]]` row."""
    where = f"[[node]][{index}]"
    _known_keys(row, NODE_KEYS, where, source)
    version = _string(row, "version", where, source)
    _version_tuple(version, f"{where} version", source)
    platform = _string(row, "platform", where, source)
    if platform not in NODE_PLATFORMS:
        raise _invalid(
            source,
            f"{where} platform is {platform!r}; one of {', '.join(NODE_PLATFORMS)} is wanted",
        )
    return NodeRuntime(
        version=version,
        platform=platform,
        sha256=_digest(row, "sha256", where, source),
        url=_url(row, "url", where, source),
    )


def _schema(document: dict[str, object], source: str) -> int:
    """The top-level `schema`, refused when absent, non-integer or from a newer grammar."""
    value = document.get("schema")
    if isinstance(value, bool) or not isinstance(value, int):
        raise _invalid(source, "the top-level `schema` key is missing or is not an integer")
    if value not in TOOLCHAIN_MANIFEST_SCHEMAS:
        raise ConfigError(
            f"{source}: schema = {value} is a Toolchain register this build cannot read "
            f"(supported: {sorted(TOOLCHAIN_MANIFEST_SCHEMAS)})",
            fix="pip install --upgrade omniweave",
        )
    return value


def parse_manifest(text: str, *, source: str) -> ToolchainManifest:
    """Parse and validate a Toolchain register's TOML text. `source` names it in every message.

    Order: TOML -> `schema` -> unknown top-level keys -> `[[toolchain]]` rows -> `[[node]]` rows ->
    uniqueness. `schema` first for the reason `card_schema` is read first (04-driver-system.md
    section 5.3): a register from a newer grammar must be refused as too new rather than misread as
    malformed, because those two faults have opposite fixes -- upgrade the tool, or edit the file.

    Every refusal is a `ConfigError` naming the row index, the key and the offending value. A
    register is hand-written and reviewed, so a message that says only "invalid" costs a reviewer
    the diff.
    """
    try:
        document = tomllib.loads(text)
    except tomllib.TOMLDecodeError as exc:
        raise _invalid(source, f"not valid TOML: {exc}") from exc

    schema = _schema(document, source)
    unknown = sorted(set(document) - {"schema", "toolchain", "node"})
    if unknown:
        raise _invalid(source, f"unknown top-level key(s) {', '.join(unknown)}")

    toolchains = tuple(
        _toolchain(row, index, source)
        for index, row in enumerate(_rows(document, "toolchain", source))
    )
    nodes = tuple(
        _node(row, index, source) for index, row in enumerate(_rows(document, "node", source))
    )
    _unique(
        [row.name for row in toolchains],
        "[[toolchain]] name",
        source,
    )
    _unique(
        [f"{row.version} {row.platform}" for row in nodes],
        "[[node]] (version, platform)",
        source,
    )
    return ToolchainManifest(schema=schema, source=source, toolchains=toolchains, nodes=nodes)


def _unique(values: list[str], what: str, source: str) -> None:
    """Refuse a repeated row identity.

    Two `[[toolchain]]` rows named `deck` would make "the digest" ambiguous, and an ambiguous digest
    is the same defect as an absent one; two `[[node]]` rows for one `(version, platform)` would let
    `ow doctor --runtime` verify against whichever the reader happened to reach first.
    """
    seen: set[str] = set()
    for value in values:
        if value in seen:
            raise _invalid(source, f"{what} {value!r} appears twice")
        seen.add(value)


def read_manifest(path: Path) -> ToolchainManifest:
    """Read and validate `tools/toolchains.toml` from `path`.

    An unreadable file is a `ConfigError` and never an `OSError`, a `KeyError` or a silent empty
    default -- 11-repo-layout.md section 2.6 rule 3, the rule `omniweave_core.errors.load_register`
    already follows for `codes.toml`, which is the same class of in-tree register.

    Read whole and unbounded, like `codes.toml`: it is an in-tree, in-wheel, reviewed file rather
    than an input, so 14-security.md section 2.2's bounded reader (whose subject is a fetched
    artefact) does not apply. Recorded here so the choice is visible rather than assumed.
    """
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        raise ConfigError(
            f"{path} is not a readable Toolchain register: {exc}",
            fix=f"restore {MANIFEST_NAME}, or reinstall the distribution that carries it",
        ) from exc
    return parse_manifest(text, source=str(path))


# --------------------------------------------------------------------------------------------
# 5. `run()`: one Toolchain invocation over `omniweave-target/1`. D810.
# --------------------------------------------------------------------------------------------

PROTOCOL: Final[str] = "omniweave-target/1"
"""The control protocol's name, sent in the host's `hello` (glossary.md, `omniweave-target/1`)."""

VERBS: Final[frozenset[str]] = frozenset({"validate", "compile", "project"})
"""The three requests section 3.2 prints between `ready` and `progress*`."""

BUNDLE_FILE: Final[str] = "bundle.tar.gz"
"""Ruling 3: the verified archive kept in the install directory, re-hashed on every invocation."""

RECEIPT: Final[str] = "out/receipt.json"
"""Ruling 6: the receipt a `compile` writes, JobDir-relative. Exit 0 iff it was written."""

STDOUT_MAX_BYTES: Final[int] = 1 << 20
"""Ruling 5: stdout is control only, "under 1 MiB per invocation"."""

BUNDLE_MAX_BYTES: Final[int] = 256 << 20
"""Ruling 3: the most of an archive read into memory to hash it and take its entry."""

GRACE_NS: Final[int] = 5_000_000_000
"""Ruling 7: SIGKILL at +5 s after the SIGTERM a timeout sends."""

ENV_ALLOWLIST: Final[tuple[str, ...]] = ("SYSTEMROOT", "WINDIR", "TEMP", "TMP", "TMPDIR")
"""Ruling 4: what the child's environment may carry from the host's, and nothing else."""

_EXIT_MISSING: Final[int] = 64
_FIX_FAILED: Final[str] = "ow explain OW-T-533"


@dataclass(frozen=True, slots=True)
class ToolchainContext:
    """What `run()` reads of the host: its home, its environment, its node rows and its clock."""

    home: Path
    """`$OMNIWEAVE_HOME`: the installed bundles and runtimes live under it (ruling 3)."""
    env: Mapping[str, str]
    """The host's environment, read for `OMNIWEAVE_NODE`, `PATH` and the allowlist (ruling 4)."""
    nodes: tuple[NodeRuntime, ...]
    """The register's `[[node]]` rows; the ladder's second rung looks for an installed one."""
    platform: str
    """This host's `NODE_PLATFORMS` tag, `win-x64`."""
    scratch: Path
    """Where the verified entry is written for this invocation (ruling 3)."""
    clock: Clock
    """The deadline's clock (ruling 7): library code reads no ambient time."""


@dataclass(frozen=True, slots=True)
class ToolchainResult:
    """One completed request: the child's `result` frame and what the host observed of it."""

    status: Literal["ok", "blocked"]
    result: Mapping[str, Any]
    """The `result` frame without its `t`: what the request returned."""
    progress: tuple[tuple[int, int], ...]
    exit_code: int
    receipt: Path | None
    node: Path
    stderr_tail: str
    """The last of the child's stderr, kept for a human and never parsed (ruling 5)."""


def install_dir(spec: ToolchainSpec, home: Path) -> Path:
    """Ruling 3: `$OMNIWEAVE_HOME/toolchains/<name>@<version>-<sha256>/`, the digest in the path."""
    digest = spec.bundle_sha256.removeprefix("sha256:")
    return home / "toolchains" / f"{spec.name}@{spec.version}-{digest}"


def resolve_node(spec: ToolchainSpec, ctx: ToolchainContext) -> Path:
    """Ruling 2: section 3.2's ladder, or `CapabilityMissing` naming the install."""
    explicit = ctx.env.get("OMNIWEAVE_NODE", "")
    if explicit:
        path = Path(explicit)
        if not path.is_file():
            raise CapabilityMissing(
                f"OMNIWEAVE_NODE names {explicit}, which is not a file",
                missing=("node",),
                fix="unset OMNIWEAVE_NODE, or point it at a node executable",
                symbol="OW_TARGET_TOOLCHAIN_MISSING",
            )
        return path
    binary = "node.exe" if ctx.platform.startswith("win-") else "node"
    for row in ctx.nodes:
        if row.platform != ctx.platform or not spec.node_range.accepts(row.version):
            continue
        installed = ctx.home / "node" / f"{row.version}-{row.platform}" / "bin" / binary
        if installed.is_file():
            return installed
    found = shutil.which(binary, path=ctx.env.get("PATH", ""))
    if found is not None and spec.node_range.accepts(_node_version(Path(found), ctx)):
        return Path(found)
    raise CapabilityMissing(
        f"no node satisfies {spec.name}'s node_range {spec.node_range.text!r}",
        missing=("node",),
        fix=f"ow targets install {spec.name}",
        symbol="OW_TARGET_TOOLCHAIN_MISSING",
    )


def _node_version(node: Path, ctx: ToolchainContext) -> str:
    """What `node --version` prints, or `""` for a binary that will not say (ruling 2)."""
    try:
        done = subprocess.run(  # noqa: S603 -- argv is a list, shell=False
            [str(node), "--version"],
            capture_output=True,
            env=_child_env(ctx),
            timeout=10,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return ""
    return done.stdout.decode("ascii", "replace").strip()


def _child_env(ctx: ToolchainContext) -> dict[str, str]:
    """Ruling 4: the allowlist's variables the host has, and no others."""
    return {key: ctx.env[key] for key in ENV_ALLOWLIST if key in ctx.env}


def _verified_entry(spec: ToolchainSpec, ctx: ToolchainContext) -> Path:
    """Ruling 3: the archive's full sha256 checked, and its entry written out to run."""
    archive = install_dir(spec, ctx.home) / BUNDLE_FILE
    if not archive.is_file():
        raise CapabilityMissing(
            f"{spec.name}@{spec.version} is not installed: no {archive}",
            missing=(f"toolchain:{spec.name}",),
            fix=f"ow targets install {spec.name}",
            symbol="OW_TARGET_TOOLCHAIN_MISSING",
        )
    if archive.stat().st_size > BUNDLE_MAX_BYTES:
        raise _digest_refused(spec, f"{archive} is over {BUNDLE_MAX_BYTES} bytes")
    data = archive.read_bytes()
    actual = "sha256:" + hashlib.sha256(data).hexdigest()
    if actual != spec.bundle_sha256:
        raise _digest_refused(spec, f"{archive} hashes to {actual}, not {spec.bundle_sha256}")
    try:
        with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as bundle:
            member = bundle.getmember(spec.entry)
            handle = bundle.extractfile(member)
            body = b"" if handle is None else handle.read()
    except (KeyError, tarfile.TarError, OSError) as exc:
        raise _failed(f"{archive} holds no file {spec.entry}: {type(exc).__name__}") from exc
    if handle is None:
        raise _failed(f"{archive}'s {spec.entry} is not a file")
    entry = ctx.scratch / f"{spec.name}@{spec.version}" / spec.entry
    entry.parent.mkdir(parents=True, exist_ok=True)
    entry.write_bytes(body)
    return entry


def _digest_refused(spec: ToolchainSpec, detail: str) -> TargetError:
    return TargetError(
        f"{spec.name}@{spec.version}'s bundle fails its digest: {detail}; nothing is fetched",
        symbol="OW_TARGET_TOOLCHAIN_DIGEST",
        fix=f"ow targets install {spec.name}   # a fresh copy, verified against the register",
    )


def _failed(detail: str) -> TargetError:
    return TargetError(detail, symbol="OW_TARGET_TOOLCHAIN_FAILED", fix=_FIX_FAILED)


def run(
    spec: ToolchainSpec,
    job_dir: Path,
    *,
    timeout_s: float,
    ctx: ToolchainContext,
    verb: str = "compile",
    request: Mapping[str, Any] | None = None,
) -> ToolchainResult:
    """Rulings 1-7: one request to a fresh child, its `result`, and the child reaped."""
    if verb not in VERBS:
        raise ValueError(f"verb {verb!r} is not one of {sorted(VERBS)}")
    node = resolve_node(spec, ctx)
    entry = _verified_entry(spec, ctx)
    deadline = ctx.clock.monotonic_ns() + int(timeout_s * 1e9)
    child = _Child.spawn((str(node), str(entry)), job_dir, _child_env(ctx))
    try:
        child.send({"t": "hello", "proto": PROTOCOL, "verb": verb})
        _ready(spec, child.frame(deadline, ctx.clock))
        child.send({**(request or {}), "t": verb})
        progress: list[tuple[int, int]] = []
        frame = child.frame(deadline, ctx.clock)
        while frame.get("t") == "progress":
            progress.append((int(frame.get("done", 0)), int(frame.get("total", 0))))
            frame = child.frame(deadline, ctx.clock)
        _result(spec, verb, frame)
        child.send({"t": "bye"})
        code = child.exit(deadline, ctx.clock)
    except BaseException as exc:
        child.reap()
        if child.proc.returncode == _EXIT_MISSING:
            raise _missing(spec) from exc
        raise
    receipt = job_dir / RECEIPT
    written = receipt.is_file()
    if code == _EXIT_MISSING:
        raise _missing(spec)
    if verb == "compile" and (code == 0) != written:
        raise _failed(
            f"{spec.name} exited {code} {'with' if written else 'without'} {RECEIPT}: "
            "a compile exits 0 iff it wrote a receipt"
        )
    if verb != "compile" and frame["status"] == "ok" and code != 0:
        raise _failed(f"{spec.name} answered {verb} ok and exited {code}")
    return ToolchainResult(
        status=frame["status"],
        result={k: v for k, v in frame.items() if k != "t"},
        progress=tuple(progress),
        exit_code=code,
        receipt=receipt if written else None,
        node=node,
        stderr_tail=child.stderr.tail().decode("utf-8", "replace"),
    )


def _missing(spec: ToolchainSpec) -> CapabilityMissing:
    """Ruling 6: a child exiting 64, at any point, has no runtime of its own."""
    return CapabilityMissing(
        f"{spec.name} exited 64: its own runtime is missing",
        missing=(f"toolchain:{spec.name}",),
        fix=f"ow targets install {spec.name}",
        symbol="OW_TARGET_TOOLCHAIN_MISSING",
    )


def _ready(spec: ToolchainSpec, frame: Mapping[str, Any]) -> None:
    """Ruling 6: the child's first frame names the spec's toolchain and version."""
    if (frame.get("t"), frame.get("toolchain"), frame.get("version")) != (
        "ready",
        spec.name,
        spec.version,
    ):
        raise _failed(f"{spec.name}'s first frame is not its ready: {_shown(frame)}")


def _result(spec: ToolchainSpec, verb: str, frame: Mapping[str, Any]) -> None:
    """Ruling 6: after the progress frames, one `result` whose status is `ok` or `blocked`."""
    if frame.get("t") != "result" or frame.get("status") not in {"ok", "blocked"}:
        raise _failed(f"{spec.name} answered {verb} with {_shown(frame)}")


_SHOWN_MAX: Final[int] = 200
"""The most of a frame a refusal quotes."""


def _shown(frame: Mapping[str, Any]) -> str:
    text = json.dumps(dict(frame), sort_keys=True)
    return text if len(text) <= _SHOWN_MAX else text[:_SHOWN_MAX] + "..."


class _Child:
    """One spawned Toolchain: its pipes, its frames, its stderr ring, and how to reap it."""

    def __init__(self, proc: subprocess.Popen[bytes], job: JobObject | None) -> None:
        self.proc = proc
        self.job = job
        self.stderr = StderrRing()
        self.frames: queue.Queue[dict[str, Any] | str | None] = queue.Queue()
        threading.Thread(target=self._read, name="ow-s2-stdout", daemon=True).start()
        threading.Thread(target=self._drain, name="ow-s2-stderr", daemon=True).start()

    @classmethod
    def spawn(cls, argv: tuple[str, ...], cwd: Path, env: Mapping[str, str]) -> _Child:
        """Ruling 4: `cwd` the JobDir, the allowlisted env, and the whole tree reapable."""
        windows = sys.platform == "win32"
        job = JobObject() if windows else None
        try:
            proc = subprocess.Popen(  # noqa: S603 -- argv is a tuple, shell=False, cwd is explicit
                list(argv),
                cwd=cwd,
                env=dict(env),
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                shell=False,
                close_fds=True,
                creationflags=CREATE_SUSPENDED if windows else 0,
                start_new_session=not windows,
            )
        except OSError as exc:
            if job is not None:
                job.close()
            raise _failed(f"{argv[0]} would not start: {type(exc).__name__}") from exc
        if job is not None:
            try:
                job.admit(proc.pid)
            except BaseException:
                proc.kill()
                proc.wait()
                job.close()
                raise
        return cls(proc, job)

    def _read(self) -> None:
        """Ruling 5: each stdout line a frame, and no more than `STDOUT_MAX_BYTES` of them."""
        seen = 0
        stream = self.proc.stdout
        try:
            while stream is not None:
                line = stream.readline(STDOUT_MAX_BYTES - seen + 1)
                if not line:
                    break
                seen += len(line)
                if seen > STDOUT_MAX_BYTES:
                    self.frames.put(f"stdout passed {STDOUT_MAX_BYTES} bytes")
                    return
                try:
                    frame = json.loads(line)
                except ValueError:
                    self.frames.put("a stdout line is not a JSON frame")
                    return
                if not isinstance(frame, dict):
                    self.frames.put("a stdout frame is not a JSON object")
                    return
                self.frames.put(frame)
        except (OSError, ValueError):  # pragma: no cover -- the pipe closed under us
            pass
        finally:
            self.frames.put(None)

    def _drain(self) -> None:
        """Ruling 5: stderr into its ring until EOF, never parsed."""
        stream = self.proc.stderr
        try:
            for chunk in iter(lambda: stream.read(4096), b"") if stream is not None else ():
                self.stderr.feed(chunk)
        except (OSError, ValueError):  # pragma: no cover -- the pipe closed under us
            pass

    def send(self, frame: Mapping[str, Any]) -> None:
        stream = self.proc.stdin
        if stream is None:  # pragma: no cover -- PIPE was requested
            raise _failed("the child has no stdin")
        try:
            stream.write(json.dumps(dict(frame), separators=(",", ":")).encode("utf-8") + b"\n")
            stream.flush()
        except OSError as exc:
            raise _failed(f"the child closed its stdin before {frame.get('t')}") from exc

    def frame(self, deadline: int, clock: Clock) -> dict[str, Any]:
        """Ruling 7: the next frame before `deadline`, or the refusal saying why there is none."""
        left = (deadline - clock.monotonic_ns()) / 1e9
        try:
            got = self.frames.get(timeout=max(left, 0.0))
        except queue.Empty:
            raise _failed(
                f"the child sent no frame before its deadline ({left:.1f} s left)"
            ) from None
        if got is None:
            raise _failed("the child closed stdout before its result")
        if isinstance(got, str):
            raise _failed(got)
        return got

    def exit(self, deadline: int, clock: Clock) -> int:
        """Ruling 7: the child's exit status after `bye`, within what is left of the deadline."""
        try:
            code = self.proc.wait(timeout=max((deadline - clock.monotonic_ns()) / 1e9, 0.0))
        except subprocess.TimeoutExpired:
            raise _failed("the child did not exit after bye before its deadline") from None
        self._close()
        return code

    def reap(self) -> None:
        """Ruling 7: SIGTERM, SIGKILL at +5 s, the whole tree; a job object on Windows."""
        if self.proc.poll() is None:
            if self.job is not None:
                self.job.terminate()
            elif sys.platform != "win32":  # pragma: no cover -- POSIX
                _kill_group(self.proc)
            self.proc.wait()
        self._close()

    def _close(self) -> None:
        for stream in (self.proc.stdin, self.proc.stdout, self.proc.stderr):
            if stream is not None:
                with contextlib.suppress(OSError):
                    stream.close()
        if self.job is not None and not self.job.closed:
            self.job.close()


if sys.platform != "win32":  # pragma: no cover -- POSIX

    def _kill_group(proc: subprocess.Popen[bytes]) -> None:
        """Ruling 7's POSIX half: SIGTERM to the group, SIGKILL at +5 s."""
        with contextlib.suppress(ProcessLookupError):
            os.killpg(proc.pid, signal.SIGTERM)
        try:
            proc.wait(timeout=GRACE_NS / 1e9)
        except subprocess.TimeoutExpired:
            with contextlib.suppress(ProcessLookupError):
                os.killpg(proc.pid, signal.SIGKILL)
