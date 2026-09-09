"""G18 -- the axis gate: a byte diff over ``tools/config_axes.toml``, and exact coverage.

G18 is not merely a byte diff. 02-architecture.md section 8.3 states three distinct failure
conditions over the axis lists, and the estimation basis for W1.4 (16-roadmap.md) names the second
as "the exact-coverage assertion -- the assertion that was missing while sixteen shipped config keys
matched no pattern at all":

1. **UNCLASSIFIED** -- a key in ``omniweave.toml.example`` that no pattern matches. Section 8.3:
   "An unclassified key fails CI and is treated at runtime as ``semantic``: fail expensive, never
   wrong." A key with no axis cannot be digested, so a silently ignored key is a config value with
   no effect, no source and no digest contribution (section 8.2).
2. **TWO GLOBS** -- "two globs matching one key is a G18 failure, not a precedence puzzle". The
   runtime half of this property is already wired: ``omniweave_core.config.resolve_key`` raises
   ``OW_CONFIG_GLOB_ARITY`` with the fix "make one pattern in tools/config_axes.toml explicit so
   exactly one matches". This module is the CI half of the same property.
3. **DEAD PATTERN** -- a pattern matching no key in the example. "The union of the two axis lists
   covers every key in ``omniweave.toml.example`` EXACTLY -- neither over nor under"; ADR-3 says
   so in as many words: "a pattern matching no key fails the same 'neither over' clause".

Plus the twin, which rides the same diff: 02-architecture.md section 8.2 rules the ``OMNIWEAVE_*``
twin is declared at the key's declaration site and emitted here, so "the same G18 byte diff
therefore covers both, and A KEY WITH NO TWIN FAILS CI". A glob pattern's twin carries one ``*`` per
glob segment, because a glob twin needs one slot per instance name to substitute.

**Key enumeration** is ADR-3 decision 3's rule, and the answer flips on it: an INLINE TABLE is ONE
key and a key quoted because it holds dots is ONE SEGMENT. Under that rule the shipped example is
118 keys; under the other reading it is 131, fourteen of them uncovered. tomllib cannot tell an
inline table from a sub-table -- the PATTERN LIST can, which is why the walk below is driven by the
patterns rather than by the document's shape.

The matcher is imported, never re-implemented: ``omniweave_core.config`` is the one home of glob
arity (INV-21), and a gate that matched by its own rules would be checking a different property
than the loader enforces.
"""

from __future__ import annotations

import sys
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Final

import gen_config_axes
from omniweave_core.config import _match_segments, join_key, split_key

__all__ = [
    "DEFAULT_EXAMPLE_PATH",
    "AxisRow",
    "Finding",
    "check",
    "check_coverage",
    "enumerate_keys",
    "main",
    "read_rows",
]

REPO: Final[Path] = Path(__file__).resolve().parents[1]
AXES_PATH: Final[Path] = REPO / "tools" / "config_axes.toml"
DEFAULT_EXAMPLE_PATH: Final[Path] = REPO / "omniweave.toml.example"

# One code per failure condition. They are strings and not an enum because the gate's output is
# read by a human in a CI log, and a code that reads as a sentence fragment is the whole value.
BYTE_DIFF: Final[str] = "generated-file-edited"
MALFORMED: Final[str] = "axis-file-malformed"
DUPLICATE_PATTERN: Final[str] = "pattern-declared-twice"
UNCLASSIFIED_KEY: Final[str] = "unclassified-key"
TWO_GLOBS: Final[str] = "two-globs-one-key"
DEAD_PATTERN: Final[str] = "pattern-matches-nothing"
TWIN_MISSING: Final[str] = "no-twin"
TWIN_ARITY: Final[str] = "twin-arity"
EXAMPLE_MISSING: Final[str] = "example-not-committed"

AXES: Final[tuple[str, ...]] = ("semantic", "operational")


@dataclass(frozen=True, slots=True)
class Finding:
    """One G18 failure. ``fix`` is THE COMMAND OR EDIT THAT CLEARS IT, never a restatement."""

    code: str
    subject: str
    detail: str
    fix: str

    def render(self) -> str:
        return f"G18 {self.code}: {self.subject}\n    {self.detail}\n    fix: {self.fix}"


@dataclass(frozen=True, slots=True)
class AxisRow:
    """One pattern as the committed file declares it: its dotted name, its axis and its twin.

    Read from ``tools/config_axes.toml`` rather than from ``omniweave_core.config``, so that the
    coverage assertion is evaluated against THE COMMITTED FILE. Evaluating it against the registry
    would make the two checks one check and leave the file itself unasserted.
    """

    name: str
    axis: str
    env: str

    @property
    def segments(self) -> tuple[str, ...]:
        return split_key(self.name)

    @property
    def glob_count(self) -> int:
        return sum(1 for s in self.segments if s in ("*", "**"))

    @property
    def is_glob(self) -> bool:
        return self.glob_count > 0

    @property
    def env_glob_count(self) -> int:
        """Maximal runs of ``*``, not ``*`` characters: ``**`` is ONE placeholder, spelled two."""
        return sum(
            1 for i, ch in enumerate(self.env) if ch == "*" and (i == 0 or self.env[i - 1] != "*")
        )

    def matches(self, key: str) -> bool:
        return _match_segments(self.segments, split_key(key))


def read_rows(text: str) -> tuple[tuple[AxisRow, ...], tuple[Finding, ...]]:
    """Parse the axis file into rows, reporting a malformed shape rather than raising.

    A gate that raises on its own input file cannot say WHICH of the three conditions failed, and
    the register's whole value is that the CI line names the key.
    """
    findings: list[Finding] = []
    try:
        document = tomllib.loads(text)
    except tomllib.TOMLDecodeError as exc:
        return (), (
            Finding(
                MALFORMED,
                "tools/config_axes.toml",
                f"tomllib refused the file: {exc}",
                "run `uv run tools/gen_config_axes.py` -- the file is generated, not edited",
            ),
        )
    twins = document.get("env", {})
    if not isinstance(twins, dict):
        findings.append(
            Finding(
                MALFORMED,
                "[env]",
                f"[env] must be a table of pattern -> twin, got {type(twins).__name__}",
                "run `uv run tools/gen_config_axes.py`",
            )
        )
        twins = {}
    rows: list[AxisRow] = []
    seen: dict[str, str] = {}
    for axis in AXES:
        block = document.get(axis, {})
        names = block.get("keys", []) if isinstance(block, dict) else []
        if not isinstance(names, list):
            findings.append(
                Finding(
                    MALFORMED,
                    f"[{axis}] keys",
                    f"expected a list of dotted patterns, got {type(names).__name__}",
                    "run `uv run tools/gen_config_axes.py`",
                )
            )
            continue
        for name in names:
            if not isinstance(name, str):
                findings.append(
                    Finding(
                        MALFORMED,
                        f"[{axis}] keys",
                        f"a pattern must be a string, got {name!r}",
                        "run `uv run tools/gen_config_axes.py`",
                    )
                )
                continue
            if name in seen:
                findings.append(
                    Finding(
                        DUPLICATE_PATTERN,
                        name,
                        f"declared under [{seen[name]}] and again under [{axis}]; "
                        "a key has ONE axis and there is no third state",
                        f"delete one declaration site for {name} in omniweave_core.config",
                    )
                )
                continue
            seen[name] = axis
            rows.append(AxisRow(name=name, axis=axis, env=str(twins.get(name, ""))))
    return tuple(rows), tuple(findings)


def check_twins(rows: tuple[AxisRow, ...]) -> tuple[Finding, ...]:
    """Every pattern carries a declared twin, and a glob twin carries one ``*`` per glob segment."""
    findings: list[Finding] = []
    for row in rows:
        if not row.env:
            findings.append(
                Finding(
                    TWIN_MISSING,
                    row.name,
                    "no OMNIWEAVE_* twin in [env]; a key with no twin fails CI "
                    "(02-architecture.md section 8.2)",
                    f"declare env= on {row.name} in omniweave_core.config, then regenerate",
                )
            )
            continue
        if row.env_glob_count != row.glob_count:
            findings.append(
                Finding(
                    TWIN_ARITY,
                    row.name,
                    f"the pattern has {row.glob_count} glob segment(s) and the twin "
                    f"{row.env!r} has {row.env_glob_count}; a glob twin needs one slot per "
                    "glob segment to name an instance",
                    f"give {row.env} one `*` per glob segment of {row.name}",
                )
            )
    return tuple(findings)


def _hits(dotted: str, rows: tuple[AxisRow, ...]) -> tuple[AxisRow, ...]:
    return tuple(row for row in rows if row.matches(dotted))


def _may_descend(segments: tuple[str, ...], rows: tuple[AxisRow, ...]) -> bool:
    """True when some pattern lives STRICTLY BELOW ``segments`` -- so this table is not a leaf."""
    for row in rows:
        pattern = row.segments
        if len(pattern) > len(segments) and _match_segments(pattern[: len(segments)], segments):
            return True
    return False


def enumerate_keys(
    document: dict[str, object], rows: tuple[AxisRow, ...]
) -> tuple[tuple[str, ...], tuple[Finding, ...]]:
    """Every leaf key of a parsed ``omniweave.toml``, under ADR-3 decision 3's enumeration rule.

    The walk stops at a pattern match, which is what makes an inline table ONE key: the patterns,
    not the document, decide where a leaf is. A mapping that matches no pattern and has no pattern
    below it is an UNCLASSIFIED KEY -- reported, not raised, because G18 must name every offender
    in one run rather than the first.
    """
    keys: list[str] = []
    findings: list[Finding] = []

    def walk(node: dict[str, object], segments: tuple[str, ...]) -> None:
        for name, value in node.items():
            here = (*segments, name)
            dotted = join_key(here)
            hits = _hits(dotted, rows)
            if not hits and isinstance(value, dict) and _may_descend(here, rows):
                walk(value, here)
                continue
            keys.append(dotted)
            globs = tuple(row for row in hits if row.is_glob)
            if not hits:
                findings.append(
                    Finding(
                        UNCLASSIFIED_KEY,
                        dotted,
                        "no pattern in either axis list matches it; an unclassified key cannot "
                        "be digested and is treated at runtime as `semantic` -- fail expensive, "
                        "never wrong",
                        f"declare {dotted} with an axis in omniweave_core.config, "
                        "then run `uv run tools/gen_config_axes.py`",
                    )
                )
            elif len(hits) > 1 and len(globs) == len(hits):
                findings.append(
                    Finding(
                        TWO_GLOBS,
                        dotted,
                        f"matched by {len(globs)} glob patterns "
                        f"({', '.join(g.name for g in globs)}): that is a G18 failure, "
                        "not a precedence puzzle",
                        "make one pattern in tools/config_axes.toml explicit so exactly one "
                        "matches",
                    )
                )

    walk(document, ())
    return tuple(keys), tuple(findings)


def check_coverage(document: dict[str, object], rows: tuple[AxisRow, ...]) -> tuple[Finding, ...]:
    """The exact-coverage assertion, both directions: neither over nor under.

    UNDER is every key matched by zero patterns; OVER is every pattern matched by zero keys. The
    second direction is the one that makes "exactly" bidirectional, and it is why adding a config
    key now costs a pattern AND a line in ``omniweave.toml.example`` (ADR-3).
    """
    keys, findings = enumerate_keys(document, rows)
    dead = [row for row in rows if not any(row.matches(key) for key in keys)]
    return (
        *findings,
        *(
            Finding(
                DEAD_PATTERN,
                row.name,
                f"declared [{row.axis}] but matches no key in the example; the union of the two "
                "lists must cover the example EXACTLY -- neither over nor under",
                f"add a line for {row.name} to omniweave.toml.example, or delete its "
                "declaration site in omniweave_core.config",
            )
            for row in dead
        ),
    )


def check(axis_text: str, example_text: str, generated: str) -> tuple[Finding, ...]:
    """All of G18 over three strings: the committed file, the example, and the generator's output.

    Taking strings rather than paths is what lets the failure fixtures be adversarial documents
    rather than temporary files, and keeps the gate's decision function free of I/O.
    """
    findings: list[Finding] = []
    if axis_text != generated:
        findings.append(
            Finding(
                BYTE_DIFF,
                "tools/config_axes.toml",
                f"the committed file is {len(axis_text.encode('utf-8'))} bytes and the generator "
                f"emits {len(generated.encode('utf-8'))}; it is T-GENERATED and byte-diff gated",
                "run `uv run tools/gen_config_axes.py`; never edit the file to make a gate pass",
            )
        )
    rows, malformed = read_rows(axis_text)
    findings += malformed
    findings += check_twins(rows)
    try:
        example = tomllib.loads(example_text)
    except tomllib.TOMLDecodeError as exc:
        findings.append(
            Finding(
                MALFORMED,
                "omniweave.toml.example",
                f"tomllib refused the example: {exc}",
                "fix omniweave.toml.example -- CI tomllib.loads every TOML block it ships",
            )
        )
        return tuple(findings)
    if rows:
        findings += check_coverage(example, rows)
    return tuple(findings)


def _example_path(argv: list[str]) -> tuple[Path | None, Finding | None]:
    """Where the example lives, or the one Finding that says why the gate cannot be evaluated."""
    match argv:
        case []:
            path = DEFAULT_EXAMPLE_PATH
        case ["--example", given]:
            path = Path(given)
        case _:
            return None, Finding(
                MALFORMED,
                "argv",
                f"unexpected arguments {argv}",
                "usage: tools/gate_config_axes.py [--example PATH]",
            )
    if not path.exists():
        return None, Finding(
            EXAMPLE_MISSING,
            str(path),
            "G18's coverage assertion is stated over `omniweave.toml.example`, which is not "
            "committed; without it neither direction of 'covers it EXACTLY' can be evaluated",
            "commit omniweave.toml.example (ADR-3 consequence 3; 11-repo-layout.md section 1.1), "
            "or pass --example PATH",
        )
    return path, None


def main(argv: list[str] | None = None) -> int:
    """Exit 0 only when the byte diff holds and coverage is exact in both directions."""
    args = list(sys.argv[1:] if argv is None else argv)
    if not AXES_PATH.exists():
        sys.stdout.write(
            f"G18 {BYTE_DIFF}: {AXES_PATH} is not committed\n"
            "    fix: run `uv run tools/gen_config_axes.py`\n"
        )
        return 1
    path, problem = _example_path(args)
    if path is None:
        assert problem is not None  # noqa: S101 - the pair is exclusive by construction
        sys.stdout.write(f"{problem.render()}\n")
        return 1
    findings = check(
        AXES_PATH.read_text(encoding="utf-8"),
        path.read_text(encoding="utf-8"),
        gen_config_axes.render(),
    )
    for finding in findings:
        sys.stdout.write(f"{finding.render()}\n")
    if findings:
        sys.stdout.write(f"G18 FAILED: {len(findings)} finding(s)\n")
        return 1
    rows, _ = read_rows(AXES_PATH.read_text(encoding="utf-8"))
    sys.stdout.write(f"G18 ok: {len(rows)} patterns cover {path} exactly, one pattern per key\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
