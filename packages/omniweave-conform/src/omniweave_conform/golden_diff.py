"""The golden diff a PR comment carries: three parts, densest first, 400 lines. **D821.**

13-quality.md section 5.3: *"`ow eval golden` produces a three-part diff, ordered by information
density, and the PR comment is capped at 400 lines"*:

1. **the `shape` delta**, a table of changed counters with old, new and signed delta -- *"the
   sentence a reviewer needs: '6 fewer tables, 174 more cells' tells you what happened"*;
2. **the `pages` rollup**, per-page lines grouped by which fields changed, a count per group and
   at most three example pages, folded *"the same mechanism `Finding` uses"*;
3. **the first 40 changed `outline` lines**, unfolded, as a unified diff.

`render()` writes the three for one document from its Reductions before and after (D817, D818),
the delta from `churn.shape_delta()` (D819). `comment()` writes them for every document a change
moved, which is what a PR comment carries (D850). 16-roadmap.md W10.2's *"the PR-comment differ led
by the `shape` delta"* is this module.

## Rulings

1. **The delta's rows are `key old -> new (signed)`**, an absent side printed `-` and a value that
   is not a count printed without a sign. The plan's *"6 fewer tables"* is a reading of these rows,
   not a second rendering of them.
2. **A `pages` group is named by the sorted fields that changed**, joined by `,`. A page present
   on one side only is the group `+page` or `-page`. Groups run in descending count, then by name,
   and each carries its count and up to `finding.EXAMPLES_MAX` page labels, in page order.
   `EXAMPLES_MAX` is the three `Finding` folds to, imported so the two cannot disagree.
3. **The `outline` part is `difflib.unified_diff` with no context**, its `---`/`+++` header kept,
   cut after 40 `+` or `-` lines; a cut says how many more there were.
4. **A suppressed `pages` or `outline` diffs as its one line.** A count is all a suppressed file
   has. A side that does not exist, for a new or a lost document, has no line (D850).
5. **400 lines is the comment's, not a part's.** The parts are written in order, and a comment
   that would pass 400 is cut at 399 with a last line counting what was left out. A diff is a
   display, so cutting it loses nothing the files do not still hold.
6. **No change, no comment.** Three unchanged files render as the empty string.
7. **A comment over several documents is one comment.** Each document that changed is headed
   `document <path>:`, in the order given, and ruling 5's 400 lines bound the whole comment, not
   each document. A document with no change has no header. A new or lost document is diffed
   against three empty files, so its whole `shape` reads as the delta. (D850.)

Specified in 13-quality.md section 5.3.
"""

from __future__ import annotations

import difflib
from collections import defaultdict
from typing import TYPE_CHECKING, Final

from omniweave_core.out.finding import EXAMPLES_MAX

from omniweave_conform.churn import parse_pages, shape_delta, suppressed

if TYPE_CHECKING:
    from collections.abc import Iterable

    from omniweave_conform.churn import Delta, Reductions

__all__ = ["ABSENT", "COMMENT_LINES", "OUTLINE_LINES", "comment", "render"]

COMMENT_LINES: Final = 400
"""13:714: *"the PR comment is capped at 400 lines"*."""

OUTLINE_LINES: Final = 40
"""13:722: *"the first 40 changed `outline` lines"*."""

ABSENT: Final = "-"
ADDED: Final = "+page"
REMOVED: Final = "-page"


def render(old: Reductions, new: Reductions, *, max_lines: int = COMMENT_LINES) -> str:
    """The three parts for one document, densest first, under the comment's cap (rulings 1-6)."""
    return _capped(_parts(old, new), max_lines)


def comment(
    documents: Iterable[tuple[str, Reductions, Reductions]], *, max_lines: int = COMMENT_LINES
) -> str:
    """Ruling 7: every changed document's parts under its header, and one cap for them all."""
    lines: list[str] = []
    for doc, old, new in documents:
        parts = _parts(old, new)
        if parts:
            lines += [f"document {doc}:", *parts]
    return _capped(lines, max_lines)


def _parts(old: Reductions, new: Reductions) -> list[str]:
    return [
        *_shape_part(old.shape, new.shape),
        *_pages_part(old.pages, new.pages),
        *_outline_part(old.outline, new.outline),
    ]


def _capped(lines: list[str], max_lines: int) -> str:
    """Ruling 5."""
    if len(lines) > max_lines:
        kept = lines[: max_lines - 1]
        lines = [*kept, f"... {len(lines) - len(kept)} more lines past the {max_lines}-line cap"]
    return "".join(f"{line}\n" for line in lines)


def _shape_part(old: str, new: str) -> list[str]:
    delta = shape_delta(old, new)
    if not delta:
        return []
    return [f"shape delta ({len(delta)} counters):", *(f"  {_row(d)}" for d in delta)]


def _row(delta: Delta) -> str:
    """Ruling 1: `key old -> new (signed)`."""
    before = ABSENT if delta.old is None else delta.old
    after = ABSENT if delta.new is None else delta.new
    sign = "" if delta.signed is None else f" ({delta.signed:+d})"
    return f"{delta.key} {before} -> {after}{sign}"


def _pages_part(old: str, new: str) -> list[str]:
    if old == new:
        return []
    if suppressed(old) is not None or suppressed(new) is not None:
        return ["pages:", *_one_line_diff(old, new)]
    before, after = parse_pages(old), parse_pages(new)
    groups: dict[str, list[str]] = defaultdict(list)
    for label in sorted(before.keys() | after.keys(), key=_page_number):
        if label not in after:
            groups[REMOVED].append(label)
        elif label not in before:
            groups[ADDED].append(label)
        else:
            a, b = before[label], after[label]
            changed = sorted(name for name in a.keys() | b.keys() if a.get(name) != b.get(name))
            if changed:
                groups[",".join(changed)].append(label)
    if not groups:
        return []
    total = sum(len(labels) for labels in groups.values())
    ordered = sorted(groups.items(), key=lambda item: (-len(item[1]), item[0]))
    return [
        f"pages ({total} lines changed in {len(groups)} groups):",
        *(f"  {name} x{len(labels)} {' '.join(labels[:EXAMPLES_MAX])}" for name, labels in ordered),
    ]


def _outline_part(old: str, new: str) -> list[str]:
    """Ruling 3: the unified diff with no context, cut after 40 changed lines."""
    if old == new:
        return []
    diff = list(
        difflib.unified_diff(
            old.splitlines(), new.splitlines(), "outline", "outline", n=0, lineterm=""
        )
    )
    head, body = diff[:2], diff[2:]
    kept, changed = [], 0
    for line in body:
        if line.startswith(("+", "-")):
            if changed == OUTLINE_LINES:
                break
            changed += 1
        kept.append(line)
    total = sum(1 for line in body if line.startswith(("+", "-")))
    lines = [f"outline (first {OUTLINE_LINES} changed lines):", *head, *kept]
    if total > changed:
        lines.append(f"... {total - changed} more changed outline lines")
    return lines


def _one_line_diff(old: str, new: str) -> list[str]:
    """Ruling 4: a suppressed side is its one line, the other side its header, and a side that
    does not exist nothing."""
    return [f"  {sign}{text.splitlines()[0]}" for sign, text in (("-", old), ("+", new)) if text]


def _page_number(label: str) -> int:
    return int(label[1:])
