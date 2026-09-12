"""G20 - the event vocabulary: generated, closed, levelled, and append-only against the tag.

`tools/gates.toml` states the assertion as *"event schema generated from `events.toml`"* and the
step as *"schema/event-v1.json generated from tools/events.toml"*. That is one relation between two
committed artefacts and three properties of the file on one side of it, and this script checks all
four. Each is independently falsifiable and each fails with the edit that would restore it.

**Check 1 - `tools/events.toml` is its generator's output.** Delegated to
`tools/gen_events.py --check`, which is the byte diff. T-GENERATED means *"byte-identical to its
generator's output"* (02-architecture.md section 2), so a hand-edited row is a failure even when it
parses and even when it is correct.

**Check 2 - the schema's vocabulary is the file's vocabulary, in order.** Read from the two
COMMITTED artefacts and never through `omniweave_core.events`, which is the point: both are
generated from that module, so comparing either against it would pass while they disagreed with
each other. `schema/event-v1.json`'s `properties.kind.enum` and `tools/events.toml`'s `kind` rows
are the same list in the same order, or the relation the gate's own assertion names is not true.

**Check 3 - every row carries a level, and it is one of the five.** 15-observability.md:341 makes
`level` required on every row *"including the charter's forty-eight"* and calls it the one change
to this file that is not an append. A row without one would make 15:1270's promise -- *"'which
events are warnings' is a static list a reviewer can read"* -- false for that kind.

**Check 4 - append-only against the previous tag.** A row is never removed and a `kind` is never
reused (15:283), because *"an event kind is a name a dashboard, a runbook and a test all hard-code,
so retiring one silently breaks three consumers."* The boundary is the tag and not the merge, for
`gate_migrations.py` check 6's reason: a tag is what published the name to those three consumers.
With no previous tag reachable this check reports `SKIP` on its own line and the gate stays green,
because a repository with nothing published has removed nothing.

The append-only check is stated as a PREFIX equality rather than a set inclusion. A set check would
pass a change that reordered the published rows, and order is not decoration: the file is *"append
order; nothing is renumbered"* (charter.md:4458), and a reader comparing two versions of it reads
the diff.

Exit 0 clean, 1 with one `G20 FAIL` block per finding.
Specified in 15-observability.md section 3.1, _notes/charter.md:4456, 11-repo-layout.md
section 6.4, and 16-roadmap.md:548 (P4 W4.8).
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess  # noqa: TID251 - check 4 diffs against a tag and `git` is its only reader.
import sys
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Final

sys.path.insert(0, str(Path(__file__).resolve().parent))

import gen_events

__all__ = [
    "EVENTS_PATH",
    "LEVELS",
    "SCHEMA_PATH",
    "Finding",
    "check_append_only",
    "check_generated",
    "check_levels",
    "check_schema_agrees",
    "main",
    "previous_tag",
    "tagged_kinds",
]

REPO: Final[Path] = Path(__file__).resolve().parents[1]
EVENTS_PATH: Final[Path] = REPO / "tools" / "events.toml"
SCHEMA_PATH: Final[Path] = REPO / "schema" / "event-v1.json"
EVENTS_PATHSPEC: Final = "tools/events.toml"

LEVELS: Final[tuple[str, ...]] = ("debug", "info", "notice", "warn", "error")
"""15-observability.md:1273's five, in ascending order. Transcribed, so a sixth fails here."""

FAIL_INDENT: Final = "    "


@dataclass(frozen=True, slots=True)
class Finding:
    """One failure, with the edit that clears it. Never a bare assertion."""

    headline: str
    detail: tuple[str, ...] = ()

    def render(self) -> str:
        return "\n".join((f"G20 FAIL: {self.headline}", *self.detail))


def _rows(path: Path) -> list[dict[str, object]]:
    parsed = tomllib.loads(path.read_text(encoding="utf-8"))
    events = parsed.get("event", [])
    return [row for row in events if isinstance(row, dict)]


def kinds_in(path: Path) -> tuple[str, ...]:
    """Every `kind` in the committed TOML, in file order."""
    return tuple(str(row["kind"]) for row in _rows(path) if "kind" in row)


# ---------------------------------------------------------------------------
# Check 1: the file is its generator's output
# ---------------------------------------------------------------------------


def check_generated() -> tuple[Finding, ...]:
    """`tools/gen_events.py --check`, whose own exit code is the byte diff."""
    if gen_events.main(["--check"]) == 0:
        return ()
    return (
        Finding(
            headline="tools/events.toml is not byte-identical to its generator's output.",
            detail=(
                FAIL_INDENT + "It is T-GENERATED (02-architecture.md section 2 row 50), so the",
                FAIL_INDENT + "declaration site is omniweave_core.events._DECLARATIONS.",
                FAIL_INDENT + "fix: uv run tools/gen_events.py",
            ),
        ),
    )


# ---------------------------------------------------------------------------
# Check 2: the schema's vocabulary is the file's vocabulary
# ---------------------------------------------------------------------------


def _schema_kinds() -> tuple[str, ...] | Finding:
    if not SCHEMA_PATH.is_file():
        return Finding(
            headline=f"{SCHEMA_PATH.relative_to(REPO).as_posix()} is not committed.",
            detail=(FAIL_INDENT + "fix: uv run tools/schemagen.py emit",),
        )
    document = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    kind = document.get("properties", {}).get("kind", {})
    values = kind.get("enum")
    if not isinstance(values, list):
        return Finding(
            headline="schema/event-v1.json's `kind` property carries no closed `enum`.",
            detail=(
                FAIL_INDENT + "The vocabulary is closed (15-observability.md:283) and schema/ is",
                FAIL_INDENT + "the language-neutral contract (11-repo-layout.md section 3.1), so a",
                FAIL_INDENT + "`kind` of any string tells a second-language reader nothing.",
                FAIL_INDENT + "fix: annotate Event.kind with EventKind and re-emit.",
            ),
        )
    return tuple(str(value) for value in values)


def check_schema_agrees() -> tuple[Finding, ...]:
    """The two committed artefacts carry one vocabulary, in one order."""
    schema = _schema_kinds()
    if isinstance(schema, Finding):
        return (schema,)
    declared = kinds_in(EVENTS_PATH)
    if schema == declared:
        return ()
    missing = [kind for kind in declared if kind not in schema]
    extra = [kind for kind in schema if kind not in declared]
    detail = [
        FAIL_INDENT + f"tools/events.toml has {len(declared)} rows and the schema enum has "
        f"{len(schema)}.",
    ]
    if missing:
        detail.append(FAIL_INDENT + f"in the file and not the schema: {', '.join(missing)}")
    if extra:
        detail.append(FAIL_INDENT + f"in the schema and not the file: {', '.join(extra)}")
    if not missing and not extra:
        detail.append(FAIL_INDENT + "same members, different order; append order is not decoration")
    detail.append(FAIL_INDENT + "fix: uv run tools/gen_events.py && uv run tools/schemagen.py emit")
    return (
        Finding(
            headline="schema/event-v1.json and tools/events.toml disagree about the vocabulary.",
            detail=tuple(detail),
        ),
    )


# ---------------------------------------------------------------------------
# Check 3: every row carries one of the five levels
# ---------------------------------------------------------------------------


def check_levels() -> tuple[Finding, ...]:
    """15:341's not-an-append: `level` is required on every row, including the charter's 48."""
    findings: list[Finding] = []
    for row in _rows(EVENTS_PATH):
        kind = row.get("kind", "<no kind>")
        level = row.get("level")
        if level is None:
            findings.append(
                Finding(
                    headline=f"{kind} declares no level.",
                    detail=(
                        FAIL_INDENT + "15-observability.md:341 makes `level` required on every",
                        FAIL_INDENT + "row, so that which events are warnings is a static list.",
                        FAIL_INDENT + "fix: give the EventSpec a Level and regenerate.",
                    ),
                )
            )
        elif level not in LEVELS:
            findings.append(
                Finding(
                    headline=f"{kind} declares level {level!r}, which is not one of {LEVELS}.",
                    detail=(
                        FAIL_INDENT + "15-observability.md:1273's table is the whole vocabulary.",
                        FAIL_INDENT + "fix: use one of the five, or amend the table first.",
                    ),
                )
            )
    return tuple(findings)


# ---------------------------------------------------------------------------
# Check 4: append-only against the previous tag
# ---------------------------------------------------------------------------


def _git(*arguments: str) -> tuple[int, str]:
    """`git <arguments>` in the repository, or `(-1, reason)` when git cannot be run at all."""
    executable = shutil.which("git")
    if executable is None:
        return -1, "git is not on PATH"
    completed = subprocess.run(  # noqa: S603 - fixed argv, no shell, argv[0] from `shutil.which`.
        [executable, *arguments],
        cwd=REPO,
        capture_output=True,
        text=True,
        check=False,
    )
    if completed.returncode != 0:
        return completed.returncode, completed.stderr.strip() or completed.stdout.strip()
    return 0, completed.stdout


def previous_tag() -> str | None:
    """The most recent tag reachable from HEAD, or `None`.

    `git describe --tags --abbrev=0`, which is `gate_migrations.py`'s choice and for its reason: the
    boundary is the last release this history descends from, and a tag on an unrelated branch has
    published nothing to this line of work.
    """
    code, output = _git("describe", "--tags", "--abbrev=0")
    if code != 0 or not output.strip():
        return None
    return output.strip()


_KIND_RE: Final = re.compile(r'^kind\s*=\s*"([^"]+)"', re.MULTILINE)


def tagged_kinds(tag: str) -> tuple[str, ...] | None:
    """What `tools/events.toml` held at `tag`, in file order, or `None` if it held nothing.

    Parsed with a regex rather than `tomllib` on purpose: the file at an older tag may have a shape
    this version's parser does not expect -- the charter's rows carried no `level` -- and a
    `TypeError` while reading history would turn an append-only check into a crash. One anchored
    line pattern reads a `kind` out of any version of the shape.
    """
    code, blob = _git("show", f"{tag}:{EVENTS_PATHSPEC}")
    if code != 0:
        return None
    return tuple(_KIND_RE.findall(blob))


def check_append_only() -> tuple[tuple[Finding, ...], str]:
    """`(findings, note)`. The note is printed whether or not there is a finding."""
    tag = previous_tag()
    if tag is None:
        return (), "SKIP (no previous tag - nothing has been published to remove)"
    published = tagged_kinds(tag)
    if published is None:
        return (), f"SKIP ({tag} carries no {EVENTS_PATHSPEC})"
    current = kinds_in(EVENTS_PATH)
    if current[: len(published)] == published:
        added = len(current) - len(published)
        return (), f"ok against {tag}: {len(published)} published, {added} appended"
    findings: list[Finding] = []
    removed = [kind for kind in published if kind not in current]
    if removed:
        findings.append(
            Finding(
                headline=f"{', '.join(removed)} was published by {tag} and is gone.",
                detail=(
                    FAIL_INDENT + "A row is never removed and a kind is never reused",
                    FAIL_INDENT + "(15-observability.md:283): an event kind is a name a dashboard,",
                    FAIL_INDENT + "a runbook and a test all hard-code.",
                    FAIL_INDENT + "fix: restore the row and append the new work after it.",
                ),
            )
        )
    reordered = [
        kind
        for index, kind in enumerate(published)
        if index < len(current) and current[index] != kind and kind in current
    ]
    if reordered:
        findings.append(
            Finding(
                headline=f"{', '.join(reordered)} moved within the published prefix.",
                detail=(
                    FAIL_INDENT + "Ordering is append order; nothing is renumbered",
                    FAIL_INDENT + "(charter.md:4458). A reader compares two versions by diff.",
                    FAIL_INDENT + "fix: restore the declaration order in omniweave_core.events.",
                ),
            )
        )
    if not findings:  # pragma: no cover - a prefix mismatch is one of the two above.
        findings.append(
            Finding(
                headline=f"the rows {tag} published are not a prefix of the current file.",
                detail=(FAIL_INDENT + "fix: append rather than edit.",),
            )
        )
    return tuple(findings), f"FAIL against {tag}"


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if args:
        sys.stdout.write("usage: tools/gate_events.py\n")
        return 2
    if not EVENTS_PATH.is_file():
        sys.stdout.write(
            "G20 FAIL: tools/events.toml is not committed.\n"
            f"{FAIL_INDENT}fix: uv run tools/gen_events.py\n"
        )
        return 1
    findings = [*check_generated(), *check_schema_agrees(), *check_levels()]
    append_findings, note = check_append_only()
    findings.extend(append_findings)
    sys.stdout.write(f"G20 append-only: {note}\n")
    if findings:
        for finding in findings:
            sys.stdout.write(finding.render() + "\n")
        sys.stdout.write(f"G20 FAILED: {len(findings)} finding(s)\n")
        return 1
    rows = kinds_in(EVENTS_PATH)
    sys.stdout.write(
        f"G20 ok: {len(rows)} event kinds, generated, levelled, and matching "
        f"{SCHEMA_PATH.relative_to(REPO).as_posix()}\n"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
