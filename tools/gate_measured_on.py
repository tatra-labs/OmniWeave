"""Q-G8's static half: no committed scoreboard row without a complete `MeasuredOn`. **D831.**

13-quality.md section 2.1 (:95): *"`Q-G8` (static half) | `eval/results/**.json` | no committed
row without a complete ten-field `MeasuredOn`"*. Section 15 (:1992) gives the other half:
*"`MeasuredOn` frozen with no defaults (a `TypeError`, not a blank cell); the static half in T0
over committed results"*. 16-roadmap.md:981 puts `uv run tools/gate_measured_on.py  # every
published number's ten-field MeasuredOn` in P10's exit criteria.

The rule is `omniweave_conform.scoreboard.unmeasured()`'s, which builds each row's `measured_on`
through `MeasuredOn` itself. The construction half and this half therefore cannot disagree about
what complete means. This file reads the tree, prints every row that fails with its reason, and
exits. That follows the standing pattern (ledger D25).

**Every row is checked, whatever its standing.** An UNKNOWN row has no number but is still
published, and it carries its run's `MeasuredOn` like any other.

**An absent tree passes, and says so,** as `tools/gate_metric_rot.py` does: nothing is published
until `ow eval publish` first writes `eval/results/`.

## `--prose`: V10-5's other half. **D981.**

00-vision.md section 9.2's V10-5 is *"every published number carries its provenance tuple"*, and
the half above reads `eval/results/` only — so a figure in the release notes was scanned by
nothing. That is how the 0.1.0 notes came to publish a 95 ms query p50 and a ~280,000-cell memory
limit with no committed `MeasuredOn` behind either, which D978 then removed by hand.

`--prose` reads `CHANGELOG.md`, `llms.txt` and `docs/*.md`, finds every figure — a number against
a time, size, rate or share unit, or a percentile — and requires a row in
`eval/published_numbers.toml` for each. A `[[limit]]` row names the file and key that configures
it, and the gate reads that key, so a limit stated in prose and a limit shipped in a card cannot
drift apart. A `[[measured]]` row names the `eval/results/**.json` row behind the figure, and the
gate holds that row to `unmeasured()` — the same ten-field rule, so a measurement with no complete
row cannot be published. A register row matching no prose is a finding as well, the way
`tools/egress.toml`'s literals are: a register nobody prunes stops being a register.

**It is one gate with two halves, not a new `Q-G` row.** 13-quality.md section 2.1 scopes Q-G8 to
`eval/results/**.json`, and this half answers V10-5 rather than widening that row — which is also
why the default run is unchanged and the prose half is a flag.

**Registration.** A `Q-G` script, so `test_gates_register.py`'s `QG_SERIES_SCRIPTS` exempts it
with its citation.

## Exit codes

`0` every row is measured. `1` a row is not, named with its file, position, metric, slice and
reason. `2` the gate did not run: a file that is not a JSON list of rows, or a bad argument.

`--prose` shares them: `0` every published figure is backed, `1` one is not, `2` the register is
absent or malformed, or no published prose is there to read. An absent register is never a pass —
unlike `eval/results/`, prose that publishes a figure exists the moment it is written.

    uv run tools/gate_measured_on.py            # the static half, over eval/results/
    uv run tools/gate_measured_on.py --prose    # V10-5's half, over the published prose

Specified in 13-quality.md sections 2.1 and 15, 04-driver-system.md section 2.6, and
16-roadmap.md section 13.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, Final

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

REPO = Path(__file__).resolve().parent.parent

for _dist in sorted((REPO / "packages").iterdir()) if (REPO / "packages").is_dir() else []:
    _src = _dist / "src"
    if _src.is_dir() and str(_src) not in sys.path:
        sys.path.insert(0, str(_src))

from omniweave_conform.scoreboard import tree, unmeasured  # noqa: E402

__all__ = [
    "EXIT_CLEAN",
    "EXIT_FAIL",
    "EXIT_NOT_RUN",
    "REGISTRY",
    "RESULTS",
    "main",
]

EXIT_CLEAN: Final = 0
EXIT_FAIL: Final = 1
EXIT_NOT_RUN: Final = 2

RESULTS: Final = Path("eval") / "results"
FIX: Final = "re-export with ow eval publish; a committed row is never edited by hand"


class _UnreadableError(Exception):
    """A results file that is not a JSON list of objects."""


def _say(line: str) -> None:
    sys.stdout.write(line + "\n")


def _findings(files: dict[str, str]) -> tuple[int, list[str]]:
    """Every row read, and a line for each one `unmeasured()` refuses."""
    count = 0
    out = []
    for path, text in sorted(files.items()):
        try:
            rows = json.loads(text)
        except json.JSONDecodeError as exc:
            raise _UnreadableError(f"{path}: not JSON ({exc.msg}, line {exc.lineno})") from exc
        if not isinstance(rows, list) or not all(isinstance(row, dict) for row in rows):
            raise _UnreadableError(f"{path}: not a list of rows")
        for at, row in enumerate(rows, start=1):
            count += 1
            why = unmeasured(row)
            if why is not None:
                out.append(f"  {path} row {at} ({row.get('metric')}@{row.get('slice_key')}): {why}")
    return count, out


REGISTRY: Final = Path("eval") / "published_numbers.toml"
REGISTRY_SCHEMA: Final = "omniweave.published-numbers/1"
PROSE: Final = ("CHANGELOG.md", "llms.txt")
"""What this project publishes as prose, beside `docs/*.md`. `_plan/` is design, not a release."""
PROSE_FIX: Final = "state what backs it in eval/published_numbers.toml, or drop the figure"

FIGURE: Final = re.compile(
    r"(?<![\w.])\d[\d,]*(?:\.\d+)?\s?(?:ms|µs|μs|us|MiB|MB|GiB|GB|KiB|KB|%|/s)(?![\w-])"
    r"|\bp(?:50|95|99)\b",
)
"""A figure in published prose: a number against a time, size, rate or share unit, or a
percentile. Deliberately narrow -- a count ("13 questions"), a version ("1.0") and a date are not
figures, and a gate that flagged them would be a gate a reviewer learns to skip. What it does
catch is every shape the 0.1.0 notes got wrong: `95 ms`, `~280,000 cells` is a count and was
removed with it, `1 GiB`, `250 MB`, `p50`."""


@dataclass(frozen=True, slots=True)
class Claimed:
    """One registered number: where it is published, and what the register says backs it."""

    kind: str
    path: str
    text: str
    source: str
    key: str
    value: object
    results: str
    row: int

    @property
    def where(self) -> str:
        return f"{self.path}: {self.text!r}"


def _rows(doc: Mapping[str, Any], name: str) -> list[Claimed]:
    out = []
    for raw in doc.get(name, []):
        if not isinstance(raw, dict):
            raise _UnreadableError(f"{REGISTRY}: a [[{name}]] row is not a table")
        out.append(
            Claimed(
                kind=name,
                path=str(raw.get("path", "")),
                text=str(raw.get("text", "")),
                source=str(raw.get("source", "")),
                key=str(raw.get("key", "")),
                value=raw.get("value"),
                results=str(raw.get("results", "")),
                row=int(raw.get("row", 0)),
            )
        )
    return out


def registry(path: Path) -> list[Claimed]:
    """The register, or `_UnreadableError` -- an absent or malformed register is never a pass."""
    try:
        doc = tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError) as exc:
        raise _UnreadableError(f"{REGISTRY}: {exc}") from exc
    except tomllib.TOMLDecodeError as exc:
        raise _UnreadableError(f"{REGISTRY}: not TOML ({exc})") from exc
    if doc.get("schema") != REGISTRY_SCHEMA:
        raise _UnreadableError(f"{REGISTRY}: schema is {doc.get('schema')!r}")
    return _rows(doc, "limit") + _rows(doc, "measured")


def published(root: Path) -> dict[str, str]:
    """Every published prose file that exists, by its repository-relative name."""
    found = {}
    for name in PROSE:
        candidate = root / name
        if candidate.is_file():
            found[name] = candidate.read_text(encoding="utf-8")
    docs = root / "docs"
    for candidate in sorted(docs.glob("*.md")) if docs.is_dir() else []:
        found[f"docs/{candidate.name}"] = candidate.read_text(encoding="utf-8")
    return found


def _dig(doc: Mapping[str, Any], key: str) -> object:
    """A dotted key's value, or `None` when any segment is missing."""
    node: object = doc
    for segment in key.split("."):
        if not isinstance(node, dict) or segment not in node:
            return None
        node = node[segment]
    return node


def _limit_holds(root: Path, claim: Claimed) -> str | None:
    """A configured limit: the cited key must exist and still hold the cited value."""
    source = root / claim.source
    if not claim.source or not claim.key:
        return "a [[limit]] row needs both `source` and `key`"
    if not source.is_file():
        return f"no such source: {claim.source}"
    try:
        doc = tomllib.loads(source.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, tomllib.TOMLDecodeError) as exc:
        return f"{claim.source}: unreadable ({exc})"
    held = _dig(doc, claim.key)
    if held is None:
        return f"{claim.source} has no {claim.key}"
    if held != claim.value:
        return f"{claim.source}:{claim.key} is {held!r}, and this row says {claim.value!r}"
    return None


def _cited_row(root: Path, claim: Claimed) -> tuple[Mapping[str, Any] | None, str | None]:
    """The results row a `[[measured]]` row cites, or why it cannot be read."""
    if not claim.results or claim.row < 1:
        return None, "a [[measured]] row needs `results` and a 1-based `row`"
    path = root / claim.results
    if not path.is_file():
        return None, f"no such results file: {claim.results}"
    try:
        rows = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        return None, f"{claim.results}: unreadable ({exc})"
    if not isinstance(rows, list) or claim.row > len(rows):
        return None, f"{claim.results} has no row {claim.row}"
    row = rows[claim.row - 1]
    if not isinstance(row, dict):
        return None, f"{claim.results} row {claim.row} is not a row"
    return row, None


def _measured_holds(root: Path, claim: Claimed) -> str | None:
    """A measured figure: the cited results row must exist and carry a complete `MeasuredOn`."""
    row, why = _cited_row(root, claim)
    if row is None:
        return why
    missing = unmeasured(row)
    if missing is not None:
        return f"{claim.results} row {claim.row}: {missing}"
    return None


def _prose_findings(root: Path, claims: Sequence[Claimed]) -> tuple[int, list[str]]:
    """Every figure in published prose, and a line for each one the register cannot back."""
    files = published(root)
    if not files:
        raise _UnreadableError(f"none of {', '.join(PROSE)} or docs/*.md is there to read")
    seen: set[tuple[str, str]] = set()
    count = 0
    out = []
    for path, text in sorted(files.items()):
        for number, line in enumerate(text.splitlines(), start=1):
            for figure in FIGURE.finditer(line):
                count += 1
                found = figure.group(0).strip()
                backing = [claim for claim in claims if claim.path == path and claim.text in line]
                if not backing:
                    out.append(f"  {path}:{number} publishes {found!r} with nothing behind it")
                    continue
                for claim in backing:
                    seen.add((claim.path, claim.text))
                    why = (
                        _limit_holds(root, claim)
                        if claim.kind == "limit"
                        else _measured_holds(root, claim)
                    )
                    if why is not None:
                        out.append(f"  {path}:{number} {found!r}: {why}")
    for claim in claims:
        if (claim.path, claim.text) not in seen:
            out.append(f"  {REGISTRY}: {claim.where} is published nowhere -- prune the row")
    return count, out


def _prose(root: Path, register: Path) -> int:
    """V10-5's other half: 0 every published figure is backed, 1 one is not, 2 it did not run."""
    try:
        claims = registry(register)
        count, findings = _prose_findings(root, claims)
    except (OSError, UnicodeDecodeError, _UnreadableError) as exc:
        _say(f"V10-5 prose DID NOT RUN  {exc}")
        return EXIT_NOT_RUN

    _say(f"V10-5 prose  {count} figure(s) published, {len(claims)} row(s) in {REGISTRY}")
    for line in findings:
        _say(line)
    if findings:
        _say(f"  fix: {PROSE_FIX}")
    _say(f"V10-5 prose {'FAIL' if findings else 'ok'}  {len(findings)} unbacked figure(s)")
    return EXIT_FAIL if findings else EXIT_CLEAN


def main(argv: list[str] | None = None) -> int:
    """0 every row measured, 1 one is not, 2 the gate did not run."""
    parser = argparse.ArgumentParser(
        prog="gate_measured_on.py",
        description="Q-G8 static half: every eval/results/**.json row has a ten-field MeasuredOn.",
    )
    parser.add_argument("--results", type=Path, default=REPO / RESULTS, metavar="DIR")
    parser.add_argument(
        "--prose",
        action="store_true",
        help="V10-5's other half: every figure in CHANGELOG.md, llms.txt and docs/*.md is backed",
    )
    parser.add_argument("--root", type=Path, default=REPO, metavar="DIR")
    parser.add_argument("--registry", type=Path, default=None, metavar="FILE")
    try:
        args = parser.parse_args(argv)
    except SystemExit:
        return EXIT_NOT_RUN

    if args.prose:
        return _prose(args.root, args.registry or args.root / REGISTRY)

    try:
        files = tree(args.results)
        count, findings = _findings(files)
    except (OSError, UnicodeDecodeError, _UnreadableError) as exc:
        _say(f"Q-G8 DID NOT RUN  {exc}")
        return EXIT_NOT_RUN

    if not files:
        _say(f"Q-G8 ok  nothing published: no *.json under {args.results}")
        return EXIT_CLEAN
    _say(f"Q-G8  {len(files)} file(s), {count} row(s)")
    for line in findings:
        _say(line)
    if findings:
        _say(f"  fix: {FIX}")
    _say(f"Q-G8 {'FAIL' if findings else 'ok'}  {len(findings)} unmeasured row(s)")
    return EXIT_FAIL if findings else EXIT_CLEAN


if __name__ == "__main__":
    raise SystemExit(main())
