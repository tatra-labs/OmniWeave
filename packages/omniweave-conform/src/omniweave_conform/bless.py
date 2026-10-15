"""Blessing an intentional golden change: the flag, `BLESS.log`, and the reviewer rule. **D820.**

13-quality.md section 5.5 gives a bless four requirements, *"all mechanical"*:

1. **`OMNIWEAVE_BLESS=1` in the environment**, and `test_bless_flag_is_off()` -- docling's
   `tests/test_data_gen_flag.py` adopted whole -- asserting the flag is off in CI, *"so a
   contributor who leaves it exported locally cannot land a self-blessing PR"*.
2. **A `BLESS.log` row in the same commit as the reduction change**, with a reason of at least
   20 characters, in the grammar
   `<iso8601-date>\\t<git-author-email>\\t<reduction-glob>\\t<churn-class-counts>\\t<reason>`,
   one line, LF, append-only.
3. **A second reviewer once the `structural` share exceeds 20% of golden files.** The threshold
   is on `structural`, never on total files.
4. **No `unexplained` rows.** There is no override.

`plan()` turns one bless's per-file churn classes (D819) into the row to append and whether a
second reviewer is needed, or refuses. `parse_log()` and `append_only()` hold the file to its
grammar and its history, and `covers()` is Q-G3's question: does every changed Reduction have a
row in this commit? Section 5.6's schema bump is `schema_bump_only()`: masking `schema_v` must
make the diff empty.

## Rulings

1. **The environment is an argument.** `blessing(env)` reads the mapping it is given; library code
   reads no ambient state, so the caller passes `os.environ` and a test passes a dict.
2. **A row is five tab-separated fields on one line, in the plan's order.**
   - The date is `YYYY-MM-DD`: the plan says ISO 8601, and a day is the grain a reviewer reads.
   - The email holds one `@`.
   - The glob is a repository path pattern.
   - The counts are `incidental=N,structural=N,unexplained=N`, in that order.
   - The reason is at least 20 characters once stripped.

   No field may hold a tab or a newline. The file is the rows, each ending in LF.
3. **Append-only means the old file is a byte prefix of the new one.** The same check
   `codes.toml` takes. A rewritten row is not an append.
4. **A bless counts every golden file the change touched.** `unchanged` files are not golden
   churn and count in neither the numerator nor the denominator of the 20% rule. The share is
   strictly above 20%: 2 of 10 needs one reviewer and 3 of 10 two.
5. **`covers()` matches each changed Reduction path against the globs of the rows the commit
   added**, with `fnmatch` and `/` separators. A change with no new row, or a row whose glob
   matches none of the changes, is reported; the first fails Q-G3, and the second is a row that
   blesses nothing.
6. **A schema bump is masked on `schema_v=` in the header alone.** Every other byte must be equal.
   One that is not is an ordinary `structural` change, and goes through the ordinary path.
   `schema_bump()` names the two versions such a file moved between (D852).

Specified in 13-quality.md sections 5.5 and 5.6.
"""

from __future__ import annotations

import fnmatch
import re
from collections import Counter
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Final, NoReturn

from omniweave_core.errors import QualityError

from omniweave_conform.churn import CHURN_SYMBOL

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping

    from omniweave_conform.churn import Churn

__all__ = [
    "BLESS_ENV",
    "CLASSES",
    "MIN_REASON",
    "SECOND_REVIEWER_SHARE",
    "BlessPlan",
    "BlessRow",
    "Coverage",
    "append_only",
    "blessing",
    "covers",
    "parse_log",
    "plan",
    "schema_bump",
    "schema_bump_only",
]

BLESS_ENV: Final = "OMNIWEAVE_BLESS"
"""13:799, and `tools/schemagen.py`'s `BLESS_ENV`: one switch for every bless in the repository."""

BLESS_ON: Final = "1"
MIN_REASON: Final = 20
SECOND_REVIEWER_SHARE: Final = 0.20
CLASSES: Final[tuple[str, ...]] = ("incidental", "structural", "unexplained")
"""The three classes a row counts, in the plan's order (13:792)."""

SEP: Final = "\t"
FIELDS: Final = 5
_DATE: Final = re.compile(r"\A\d{4}-\d{2}-\d{2}\Z")
_EMAIL: Final = re.compile(r"\A[^@\s]+@[^@\s]+\Z")
_COUNTS: Final = re.compile(r"\Aincidental=(\d+),structural=(\d+),unexplained=(\d+)\Z")
_SCHEMA_V: Final = re.compile(r"schema_v=\S+")
_FIX_ROW: Final = "fix the BLESS.log row the message names; the file is append-only"


@dataclass(frozen=True, slots=True)
class BlessRow:
    """One `BLESS.log` row, checked at construction (ruling 2)."""

    date: str
    author: str
    glob: str
    counts: Mapping[str, int] = field(hash=False)
    reason: str

    def __post_init__(self) -> None:
        for name in ("date", "author", "glob", "reason"):
            value = getattr(self, name)
            if SEP in value or "\n" in value or "\r" in value:
                _refuse(f"BLESS.log {name} {value!r} holds a tab or a line break")
        if not _DATE.match(self.date):
            _refuse(f"BLESS.log date {self.date!r} is not YYYY-MM-DD")
        if not _EMAIL.match(self.author):
            _refuse(f"BLESS.log author {self.author!r} is not an email")
        if not self.glob.strip():
            _refuse("BLESS.log glob is empty")
        if sorted(self.counts) != sorted(CLASSES) or any(v < 0 for v in self.counts.values()):
            _refuse(f"BLESS.log counts {dict(self.counts)!r} are not the three classes")
        if len(self.reason.strip()) < MIN_REASON:
            _refuse(
                f"a bless reason is at least {MIN_REASON} characters, naming the driver version "
                f"or the code change; got {self.reason.strip()!r}"
            )

    def line(self) -> str:
        """The row as one LF-terminated line."""
        counts = ",".join(f"{cls}={self.counts[cls]}" for cls in CLASSES)
        return SEP.join((self.date, self.author, self.glob, counts, self.reason)) + "\n"


@dataclass(frozen=True, slots=True)
class BlessPlan:
    """What one bless writes, and whether it needs a second reviewer (ruling 4)."""

    row: BlessRow
    second_reviewer: bool
    structural: int
    touched: int


@dataclass(frozen=True, slots=True)
class Coverage:
    """Q-G3's answer: changes no new row blesses, and new rows that bless nothing."""

    unblessed: tuple[str, ...]
    idle: tuple[BlessRow, ...]


def blessing(env: Mapping[str, str]) -> bool:
    """Requirement 1, read from the mapping the caller passes (ruling 1)."""
    return env.get(BLESS_ENV) == BLESS_ON


def plan(
    churn: Mapping[str, Churn],
    *,
    env: Mapping[str, str],
    date: str,
    author: str,
    glob: str,
    reason: str,
) -> BlessPlan:
    """The row a bless of `churn` (file -> class) appends, or a refusal (requirements 1-4)."""
    if not blessing(env):
        raise QualityError(
            f"--bless refuses: {BLESS_ENV}={BLESS_ON} is not in the environment",
            fix=f"{BLESS_ENV}={BLESS_ON} ow eval golden --bless --reason '<why, 20+ characters>'",
        )
    unexplained = sorted(path for path, one in churn.items() if one.cls == "unexplained")
    if unexplained:
        raise QualityError(
            f"{len(unexplained)} golden file(s) changed unexplained, and there is no override: "
            f"{', '.join(unexplained)}",
            symbol=CHURN_SYMBOL,
            fix=f"ow eval golden --explain {unexplained[0]}",
        )
    tally = Counter(one.cls for one in churn.values() if one.cls != "unchanged")
    touched = sum(tally.values())
    if not touched:
        _refuse("nothing to bless: no golden file changed")
    counts = {cls: tally.get(cls, 0) for cls in CLASSES}
    row = BlessRow(date=date, author=author, glob=glob, counts=counts, reason=reason)
    structural = counts["structural"]
    return BlessPlan(
        row=row,
        second_reviewer=structural / touched > SECOND_REVIEWER_SHARE,
        structural=structural,
        touched=touched,
    )


def parse_log(text: str) -> tuple[BlessRow, ...]:
    """Every row of a `BLESS.log`, each a whole LF-terminated line (ruling 2)."""
    if text and not text.endswith("\n"):
        _refuse("BLESS.log does not end in LF: its last row was cut")
    rows = []
    for number, line in enumerate(text.splitlines(), 1):
        parts = line.split(SEP)
        if len(parts) != FIELDS:
            _refuse(f"BLESS.log:{number} has {len(parts)} fields, not {FIELDS}")
        date, author, glob, counts, reason = parts
        match = _COUNTS.match(counts)
        if match is None:
            _refuse(
                f"BLESS.log:{number} counts {counts!r} are not incidental=,structural=,unexplained="
            )
        tally: dict[str, int] = dict(zip(CLASSES, map(int, match.groups()), strict=True))
        rows.append(BlessRow(date=date, author=author, glob=glob, counts=tally, reason=reason))
    return tuple(rows)


def append_only(old: str, new: str) -> tuple[BlessRow, ...]:
    """The rows `new` appends to `old`, or a refusal when `new` rewrote any of `old` (ruling 3)."""
    if not new.startswith(old):
        _refuse("BLESS.log was rewritten, not appended to: the old file is not a prefix of the new")
    parse_log(old)
    return parse_log(new[len(old) :])


def covers(changed: Iterable[str], added: Iterable[BlessRow]) -> Coverage:
    """Q-G3: each changed Reduction under a row this commit added, and no idle row (ruling 5)."""
    paths = sorted({path.replace("\\", "/") for path in changed})
    rows = tuple(added)
    unblessed = tuple(p for p in paths if not any(fnmatch.fnmatchcase(p, r.glob) for r in rows))
    idle = tuple(r for r in rows if not any(fnmatch.fnmatchcase(p, r.glob) for p in paths))
    return Coverage(unblessed=unblessed, idle=idle)


def schema_bump_only(old: str, new: str) -> bool:
    """Section 5.6: masking `schema_v=` in the header makes the two files equal (ruling 6)."""

    def masked(text: str) -> str:
        head, sep, body = text.partition("\n")
        return _SCHEMA_V.sub("schema_v=*", head) + sep + body

    return old != new and masked(old) == masked(new)


def schema_bump(old: str, new: str) -> tuple[str, str] | None:
    """Ruling 6: the `schema_v` pair a masked-equal file moved between, or `None`."""
    if not schema_bump_only(old, new):
        return None
    before = _SCHEMA_V.search(old.partition("\n")[0])
    after = _SCHEMA_V.search(new.partition("\n")[0])
    if before is None or after is None:
        return None
    return before.group().partition("=")[2], after.group().partition("=")[2]


def _refuse(message: str) -> NoReturn:
    raise QualityError(message, fix=_FIX_ROW)
