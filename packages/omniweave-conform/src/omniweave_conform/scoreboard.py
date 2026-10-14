"""Publishing the scoreboard: `eval_scoreboard` into `eval/results/**.json`, and Q-G19. **D828.**

13-quality.md section 11.1: *"A static site generated from a committed `eval/results/**.json`
tree, **byte-diff gated** (`Q-G19`), so a scoreboard change is a reviewable diff and not a
deploy. The `.oweval` file itself is generated and `.gitignore`d; `ow eval publish` exports the
`eval_scoreboard` view into the committed JSON tree."* Every row carries `value`, `n`, `ci_lo`,
`ci_hi`, `method`, `slice_key`, `truth_kind`, `measured_on`, `witness`, `unpinned`,
`entrant_bias`, `not_measured[]`, `confounders[]` and `standing`, and Q-G19 *"fails the row if any
is missing or empty"*. Section 11.3: *"`ow eval publish` has no filter on direction."* 16-roadmap.md
W10.7 is the work item.

`export()` builds the tree's files from an `.oweval` connection; `check()` is Q-G19's row clause;
`stale()` is its byte-diff clause against a committed tree; `write()` lays the files down and
`tree()` reads them back, for Q-G27 (`omniweave_conform.rot`, D829).

## Rulings

1. **One file per `(suite, subject)`**, at `<suite>/<subject>.json`. A subject that would leave
   its directory -- a path separator, `..`, or nothing -- is refused rather than escaped.
2. **A file is canonical JSON**: a list of rows in `oweval.scoreboard()`'s order, which within one
   file is metric, slice, subject version, corpus, corpus version and run; keys sorted, two-space
   indented for a reviewer's diff, ending in a newline. The same `.oweval` writes the same bytes.
3. **Every view row is published, whatever its direction.** A `regressed` or `UNKNOWN` row is a
   row; there is no flag, filter or draft state (section 11.3).
4. **A row carries the view's columns and its run's four published fields**: `measured_on`,
   `not_measured`, `confounders` and `fairness` (where a judge's kappa lives, 13:1640). The join is
   on the `run_id` the view names (D828), so `standing` is the view's and nothing recomputes it.
5. **Q-G19 refuses a row with a required field missing, or an empty `not_measured` or
   `confounders`.** `value`, `ci_lo` and `ci_hi` are required as keys and may be `null` exactly
   when `method` is `none`: an UNKNOWN row has no number, and a `0.0` in its place would be a
   claim. `measured_on` must be a non-empty object.

Specified in 13-quality.md sections 11.1 and 11.3, and 16-roadmap.md W10.7.
"""

from __future__ import annotations

import json
from dataclasses import asdict
from typing import TYPE_CHECKING, Any, Final

from omniweave_core.errors import QualityError
from omniweave_core.store.oweval import runs, scoreboard

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping
    from pathlib import Path

__all__ = ["REQUIRED", "check", "export", "stale", "tree", "write"]

REQUIRED: Final = (
    "value",
    "n",
    "ci_lo",
    "ci_hi",
    "method",
    "slice_key",
    "truth_kind",
    "measured_on",
    "witness",
    "unpinned",
    "entrant_bias",
    "not_measured",
    "confounders",
    "standing",
)
"""13:1627-1640's required fields, in the table's order."""

_NUMBERS: Final = ("value", "ci_lo", "ci_hi")
_LISTS: Final = ("not_measured", "confounders")
_FIX: Final = "fill the run's not_measured and confounders, then ow eval publish again"


def export(connection: Any) -> dict[str, str]:
    """The tree's files, `relative path -> text`, from one `.oweval` (rulings 1-4).

    `connection` is the one `oweval.open_oweval()` returns; its type is not named here, because
    `sqlite3` is the store's alone (INV-17).
    """
    fields = runs(connection)
    grouped: dict[str, list[dict[str, Any]]] = {}
    for standing in scoreboard(connection):
        row = asdict(standing)
        row.update(fields[standing.run_id])
        grouped.setdefault(_path(standing.suite, standing.subject), []).append(row)
    out = {}
    for path, rows in sorted(grouped.items()):
        check(rows)
        out[path] = json.dumps(rows, sort_keys=True, indent=2, ensure_ascii=False) + "\n"
    return out


def check(rows: Iterable[Mapping[str, Any]]) -> None:
    """Q-G19's row clause (ruling 5): every required field present, and none empty."""
    for row in rows:
        label = (
            f"{row.get('suite')}/{row.get('subject')} {row.get('metric')}@{row.get('slice_key')}"
        )
        missing = [name for name in REQUIRED if name not in row]
        if missing:
            _refuse(f"{label}: missing {missing}")
        empty = [name for name in _LISTS if not row[name]]
        if empty:
            _refuse(f"{label}: {', '.join(empty)} empty; every benchmark has a scope")
        if not row["measured_on"] or not isinstance(row["measured_on"], dict):
            _refuse(f"{label}: measured_on is not a MeasuredOn")
        unknown = row["method"] == "none"
        blank = [name for name in _NUMBERS if row[name] is None]
        if blank and not unknown:
            _refuse(f"{label}: {blank} null with method {row['method']!r}")
        if unknown and len(blank) != len(_NUMBERS):
            _refuse(f"{label}: a number on a row whose method is none")


def stale(root: Path, files: Mapping[str, str]) -> tuple[str, ...]:
    """Q-G19's byte clause: every path whose committed bytes differ, are missing, or are extra."""
    out = []
    for path, text in sorted(files.items()):
        target = root / path
        if not target.is_file() or target.read_bytes() != text.encode("utf-8"):
            out.append(path)
    if root.is_dir():
        committed = {
            str(p.relative_to(root)).replace("\\", "/") for p in root.rglob("*.json") if p.is_file()
        }
        out.extend(sorted(committed - set(files)))
    return tuple(out)


def tree(root: Path) -> dict[str, str]:
    """A committed tree's files, `relative path -> text`, as `export()` names them. An absent
    tree publishes nothing and reads as no files, which `Path.rglob` already gives."""
    return {
        str(p.relative_to(root)).replace("\\", "/"): p.read_bytes().decode("utf-8")
        for p in sorted(root.rglob("*.json"))
        if p.is_file()
    }


def write(root: Path, files: Mapping[str, str]) -> None:
    """Lay the tree's files down under `root`, LF and UTF-8."""
    for path, text in files.items():
        target = root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(text.encode("utf-8"))


def _path(suite: str, subject: str) -> str:
    """Ruling 1."""
    for part in (suite, subject):
        if not part or part in (".", "..") or any(c in part for c in "/\\\x00"):
            _refuse(f"{part!r} cannot name a results file")
    return f"{suite}/{subject}.json"


def _refuse(message: str) -> None:
    raise QualityError(f"Q-G19: {message}", fix=_FIX)
