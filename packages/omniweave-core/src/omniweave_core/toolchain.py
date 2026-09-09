"""Seam S2's register: the reader for `tools/toolchains.toml`, and nothing that spawns.

A **Toolchain** is a digest-pinned non-Python execution bundle invoked as a one-shot child over
`omniweave-target/1`. TypeScript exists in this framework for exactly two of them -- `deck` and
`video` -- and for nothing else, because only those two OUT targets need a browser-grade layout
engine (11-repo-layout.md section 3.1). This module is the Python half's entry point, and at W1.6
it is **the manifest reader only**: `ToolchainSpec`, `NodeRuntime`, the two-table grammar and its
validation. Node resolution, the full-sha256 verification of a downloaded bundle, the spawn and the
SIGTERM -> SIGKILL + 5 s process-group reap are `run(spec, job_dir, *, timeout_s, ctx)`'s
(02-architecture.md section 2 row 16) and are not implemented here -- so this module imports no
`subprocess`, and the `TID251` allowance `pyproject.toml` reserves for it stays unused until the
runner lands.

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
"""

from __future__ import annotations

import re
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from omniweave_core.errors import ConfigError

__all__ = [
    "MANIFEST_NAME",
    "NODE_KEYS",
    "NODE_PLATFORMS",
    "RANGE_OPERATORS",
    "TOOLCHAIN_KEYS",
    "TOOLCHAIN_MANIFEST_SCHEMAS",
    "NodeRange",
    "NodeRuntime",
    "ToolchainManifest",
    "ToolchainSpec",
    "VersionClause",
    "parse_manifest",
    "read_manifest",
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
