"""Golden churn: the `shape` delta, and the class one document's change falls in. **D819.**

13-quality.md section 5.4: *"A line-count threshold on golden churn is unenforceable: a legitimate
driver upgrade changes every line of `pages`, and a reducer bug changes three. So the gate
classifies the diff into a **churn class** and gates on the class."* Three classes:

- **`incidental`**: every changed line's changed fields are digests, every count and histogram
  is unchanged, and the `shape` delta is empty. It merges with a one-line reason.
- **`structural`**: a histogram moved or a line came or went. It needs a non-empty and
  consistent `shape` delta.
- **`unexplained`**: a `pages` or `outline` change with an empty `shape` delta. It fails the
  build as `OW-Q-012`, and *"is the whole reason the classification exists"*.

The arithmetic `unexplained` rests on is declared per counter in `fixtures/goldens/
DECOMPOSITION.toml`, which `load_decomposition()` reads and `Decomposition.verify()` holds to the
families `reduce.SHAPE_FAMILIES` names. `classify()` compares one document's three Reductions
before and after (D817, D818), and `shape_delta()` is the first of section 5.3's three diff parts.

## Rulings

1. **The table covers exactly the reducer's families, both ways.** A `shape` counter that no row
   matches, and a row that matches no family, each refuse: *"in both directions"* (13:787). A
   `page_wise = false` row must carry its `reason`.
2. **`page_wise` is arithmetic, and the cross-check runs where `pages` prints the family.**
   `blocks.total` is the sum of `n=`, and `blocks.kind`, `blocks.layer`, `trust`, `quote` and
   `diag` of their histograms. A `page_wise` family `pages` does not print (`marks.kind`) is
   declared and never cross-checked. A non-page-wise one may move in `shape` alone.
3. **`unchanged` is a fourth outcome**, not a class: nothing moved, and nothing needs a reason.
4. **A digest-only change** is, in `pages`, a line whose only changed fields are `cdig` and `ldig`,
   with the same pages present. In `outline`, it is a line whose only changed fields are `cdig`,
   `ldig` and the preview, with the same addresses present. The preview moves with the text a
   `cdig` digests, and lines are keyed by address, which is positional, so two blocks trading
   places is two digest changes.
5. **With an empty `shape` delta**, digest-only changes are `incidental` and any other change is
   `unexplained`. An empty delta means the page count did not move either, which is the clause
   13:737 adds.
6. **With a non-empty delta**, each `page_wise` key's change must equal its `pages` sum's change,
   or the change is `unexplained`. That is *"a per-page rollup that disagrees with the per-document
   counters it is supposed to sum to"*. Otherwise it is `structural`.
7. **A SUPPRESSED Reduction compares by its count.** A file suppressed on both sides with the same
   `pages=` or `blocks=` changed only its would-be size: digest-only. A count change, or a file
   suppressed on one side only, is a structural change to it, and `pages` cannot be cross-checked
   then. The report says so in its reasons.

Specified in 13-quality.md sections 5.3 and 5.4.
"""

from __future__ import annotations

import fnmatch
import tomllib
from collections import Counter
from dataclasses import dataclass
from typing import TYPE_CHECKING, Final, Literal, NamedTuple

from omniweave_core.errors import QualityError

from omniweave_conform.reduce import OUTLINE_FORMAT, PAGES_FORMAT, SHAPE_FAMILIES

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping
    from pathlib import Path

__all__ = [
    "CHURN_SYMBOL",
    "Churn",
    "Decomposition",
    "Delta",
    "Reductions",
    "Row",
    "classify",
    "load_decomposition",
    "parse_pages",
    "refuse_unexplained",
    "shape_delta",
    "suppressed",
]

ChurnClass = Literal["unchanged", "incidental", "structural", "unexplained"]

CHURN_SYMBOL: Final = "OW_GOLDEN_CHURN_UNEXPLAINED"
"""`codes.toml`'s `OW-Q-012`."""

PAGE_FIELDS: Final[Mapping[str, str]] = {
    "kind": "blocks.kind.",
    "layer": "blocks.layer.",
    "trust": "trust.",
    "quote": "quote.",
    "diag": "diag.",
}
"""A `pages` histogram and the `shape` prefix its buckets sum to (ruling 2)."""

PAGE_DIGESTS: Final = frozenset({"cdig", "ldig"})
OUTLINE_DIGESTS: Final = frozenset({5, 6, 7})
"""`cdig`, `ldig` and the preview, by field position in an `outline` line (ruling 4)."""

SUPPRESSED: Final = "SUPPRESSED"
_FIX: Final = "ow eval golden --explain {file}"


class Reductions(NamedTuple):
    """One document's three Reductions, as text."""

    shape: str
    pages: str
    outline: str


@dataclass(frozen=True, slots=True)
class Row:
    """One `DECOMPOSITION.toml` row."""

    id: str
    page_wise: bool
    reason: str | None = None


@dataclass(frozen=True, slots=True)
class Decomposition:
    """The table, read and checked (ruling 1)."""

    rows: tuple[Row, ...]

    def row_for(self, key: str) -> Row:
        """The row a `shape` key falls under, or `OW-Q-012`'s refusal naming it."""
        for row in self.rows:
            if fnmatch.fnmatchcase(key, row.id):
                return row
        raise QualityError(
            f"shape counter {key!r} has no DECOMPOSITION.toml row",
            symbol=CHURN_SYMBOL,
            fix="add its row to fixtures/goldens/DECOMPOSITION.toml: is it page-wise, and why",
        )

    def verify(self, families: Iterable[str] = SHAPE_FAMILIES) -> None:
        """The table holds exactly `families`: no family without a row, no row without one."""
        ids = {row.id for row in self.rows}
        want = set(families)
        missing, extra = sorted(want - ids), sorted(ids - want)
        if missing or extra:
            raise QualityError(
                f"DECOMPOSITION.toml does not match the reducer: no row for {missing}, "
                f"rows for no family {extra}",
                symbol=CHURN_SYMBOL,
                fix="make fixtures/goldens/DECOMPOSITION.toml's ids equal reduce.SHAPE_FAMILIES",
            )


@dataclass(frozen=True, slots=True)
class Delta:
    """One changed `shape` counter. `signed` is `new - old` for counts, `None` otherwise; an
    absent side of a count is 0, of anything else `None`."""

    key: str
    old: str | None
    new: str | None
    signed: int | None


@dataclass(frozen=True, slots=True)
class Churn:
    """One document's class, its `shape` delta, and why."""

    cls: ChurnClass
    delta: tuple[Delta, ...]
    reasons: tuple[str, ...]


def load_decomposition(path: Path) -> Decomposition:
    """Read `DECOMPOSITION.toml`: unique ids, and a reason on every row that is not page-wise."""
    raw = tomllib.loads(path.read_text(encoding="utf-8"))
    rows = []
    for item in raw.get("counter", []):
        row = Row(id=str(item["id"]), page_wise=bool(item["page_wise"]), reason=item.get("reason"))
        if not row.page_wise and not row.reason:
            raise QualityError(
                f"DECOMPOSITION.toml row {row.id!r} is not page-wise and says no reason",
                symbol=CHURN_SYMBOL,
                fix="give the row a reason: the exclusion list may not grow quietly",
            )
        rows.append(row)
    ids = [row.id for row in rows]
    if len(set(ids)) != len(ids):
        raise QualityError(
            f"DECOMPOSITION.toml repeats an id: {sorted(ids)}",
            symbol=CHURN_SYMBOL,
            fix="one row per family",
        )
    return Decomposition(rows=tuple(rows))


def shape_delta(old: str, new: str) -> tuple[Delta, ...]:
    """Every counter that differs between two `shape` files, by key (section 5.3's first part)."""
    before, after = _shape(old), _shape(new)
    out = []
    for key in sorted(before.keys() | after.keys()):
        a, b = before.get(key), after.get(key)
        if a != b:
            out.append(Delta(key=key, old=a, new=b, signed=_signed(a, b)))
    return tuple(out)


def classify(old: Reductions, new: Reductions, decomposition: Decomposition) -> Churn:
    """The class of one document's change (rulings 3-7)."""
    for key in _shape(new.shape):
        decomposition.row_for(key)
    delta = shape_delta(old.shape, new.shape)
    pages = _compare_pages(old.pages, new.pages)
    outline = _compare_outline(old.outline, new.outline)
    reasons = [*pages.reasons, *outline.reasons]
    if not delta:
        if not pages.moved and not outline.moved:
            return Churn("unchanged", (), ())
        if pages.digest_only and outline.digest_only:
            return Churn("incidental", (), tuple(reasons))
        reasons.append("pages or outline changed beyond their digests, with an empty shape delta")
        return Churn("unexplained", (), tuple(reasons))
    if pages.sums is not None:
        for key in sorted({d.key for d in delta} | pages.sums.keys()):
            if not (_printed(key) and _page_wise(key, decomposition)):
                continue
            moved = next((d.signed for d in delta if d.key == key), 0) or 0
            if moved != pages.sums.get(key, 0):
                reasons.append(
                    f"{key} moved {moved:+d} in shape and {pages.sums.get(key, 0):+d} over pages"
                )
                return Churn("unexplained", delta, tuple(reasons))
    return Churn("structural", delta, tuple(reasons))


def refuse_unexplained(churn: Churn, file: str) -> None:
    """`OW-Q-012`: an `unexplained` class fails the build, and there is no override."""
    if churn.cls == "unexplained":
        raise QualityError(
            f"unexplained golden churn in {file}: {'; '.join(churn.reasons)}",
            symbol=CHURN_SYMBOL,
            fix=_FIX.format(file=file),
        )


# --------------------------------------------------------------------------------------------
# The comparisons.
# --------------------------------------------------------------------------------------------


class _Compared(NamedTuple):
    moved: bool
    digest_only: bool
    sums: dict[str, int] | None
    reasons: tuple[str, ...]


def _shape(text: str) -> dict[str, str]:
    out = {}
    for line in text.splitlines()[1:]:
        key, _, value = line.partition(" ")
        out[key] = value
    return out


def _signed(a: str | None, b: str | None) -> int | None:
    """`new - old` when both sides are counts or absent; absent counts as 0."""
    if not all(v is None or v.lstrip("-").isdigit() for v in (a, b)):
        return None
    return int(b or 0) - int(a or 0)


def _page_wise(key: str, decomposition: Decomposition) -> bool:
    return decomposition.row_for(key).page_wise


def _printed(key: str) -> bool:
    """Ruling 2: whether `pages` prints `key`'s family, which a cross-check needs."""
    return key == "blocks.total" or key.startswith(tuple(PAGE_FIELDS.values()))


def suppressed(text: str) -> dict[str, str] | None:
    """A SUPPRESSED file's `name=value` fields, or `None` for a whole one."""
    first = text.split("\n", 1)[0]
    parts = first.split(" ")
    if len(parts) < 2 or parts[1] != SUPPRESSED:  # noqa: PLR2004 -- `<format> SUPPRESSED`
        return None
    return dict(part.split("=", 1) for part in parts[2:])


def _compare_suppressed(kind: str, unit: str, old: str, new: str) -> _Compared | None:
    """Ruling 7, or `None` when neither side is suppressed."""
    a, b = suppressed(old), suppressed(new)
    if a is None and b is None:
        return None
    if a is not None and b is not None and a.get(unit) == b.get(unit):
        moved = a != b
        return _Compared(moved, True, None, (f"{kind} suppressed on both sides",) if moved else ())
    return _Compared(True, False, None, (f"{kind} suppressed on one side or its {unit} moved",))


def _compare_pages(old: str, new: str) -> _Compared:
    one_line = _compare_suppressed(PAGES_FORMAT, "pages", old, new)
    if one_line is not None:
        return one_line
    before, after = parse_pages(old), parse_pages(new)
    sums: Counter[str] = Counter()
    for label in before.keys() | after.keys():
        for key, value in _page_counts(after.get(label, {})).items():
            sums[key] += value
        for key, value in _page_counts(before.get(label, {})).items():
            sums[key] -= value
    moved = before != after
    digest_only = before.keys() == after.keys() and all(
        _changed_fields(before[label], after[label]) <= PAGE_DIGESTS for label in before
    )
    return _Compared(moved, digest_only, {k: v for k, v in sums.items() if v}, ())


def _compare_outline(old: str, new: str) -> _Compared:
    one_line = _compare_suppressed(OUTLINE_FORMAT, "blocks", old, new)
    if one_line is not None:
        return one_line
    before, after = _outline(old), _outline(new)
    moved = before != after
    digest_only = before.keys() == after.keys() and all(
        {i for i, (x, y) in enumerate(zip(before[a], after[a], strict=True)) if x != y}
        <= OUTLINE_DIGESTS
        for a in before
    )
    return _Compared(moved, digest_only, None, ())


def parse_pages(text: str) -> dict[str, dict[str, str]]:
    """A whole `pages` file's lines as `label -> {field: value}`, a histogram's value being the
    text inside its braces. Shared with the differ (D821), so the two read one format one way."""
    out = {}
    for line in text.splitlines()[1:]:
        label, *fields = line.split(" ")
        parsed = {}
        for field in fields:
            if "{" in field:
                name, _, rest = field.partition("{")
                parsed[name] = rest.rstrip("}")
            else:
                name, _, value = field.partition("=")
                parsed[name] = value
        out[label] = parsed
    return out


def _page_counts(fields: Mapping[str, str]) -> dict[str, int]:
    """A page line's counts under `shape`'s keys (ruling 2)."""
    out: dict[str, int] = {}
    if "n" in fields:
        out["blocks.total"] = int(fields["n"])
    for name, prefix in PAGE_FIELDS.items():
        for pair in filter(None, fields.get(name, "").split(",")):
            bucket, _, value = pair.rpartition(":")
            out[prefix + bucket] = int(value)
    return out


def _changed_fields(a: Mapping[str, str], b: Mapping[str, str]) -> set[str]:
    return {name for name in a.keys() | b.keys() if a.get(name) != b.get(name)}


def _outline(text: str) -> dict[str, tuple[str, ...]]:
    """`addr -> its eight fields`, the preview padded to `""` where a block has none."""
    out = {}
    for line in text.splitlines()[1:]:
        fields = line.split(" ", 7)
        out[fields[0]] = tuple(fields) + ("",) * (8 - len(fields))
    return out
