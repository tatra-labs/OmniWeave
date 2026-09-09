"""The tombstone clock: CI fails a framework tombstone past its `review_by`.

Reads `packages/omniweave-core/src/omniweave_core/drivers/tombstones/*.toml` and nothing else.
04-driver-system.md section 7.5 states the obligation in one sentence -- *"a test asserts every
vetoed id has a tombstone with a non-empty reason and a future `review_by`, and CI **fails** a
tombstone past its `review_by` date, so the refusal set cannot silently ossify"* -- and section
10.4 repeats it over the six cards shipped at release 1. This script is the CI half; the test
half is `packages/omniweave-core/tests/unit/test_tombstones.py`, which loads the same six files
through `omniweave_core.drivers.card.load_card()` and asserts the grammar. Two halves, because a
refusal set is exactly the kind of artefact that is green for years and never once shown a
violation.

**Why a clock at all.** A tombstone is a licence reading with a date on it. Clause 2(c) of the
Datalab `MODEL_LICENSE` is true today; an upstream relicence, a jurisdiction change or a
replacement driver landing would each make one of these six cards wrong, and a wrong refusal is
as expensive as a missing one -- it removes a decision that belongs to the operator. The clock
is what forces the set to be re-READ rather than inherited.

**The interval, and why 90 days.** `review_by = "2026-12-03"` on all six, which is 88 days after
this set was authored on 2026-09-06. The number is not chosen here: 17-risks.md section 1 sets
`[register] review_every_days = 90` for the risk register, R-L1 is the row whose second
mitigation *is* this tombstone set, its owner is the `licence` role, and its own row reads
`reviewed_at = "2026-09-04"` / `review_by = "2026-12-03"`. Firing the tombstone clock on any
other date would make the licence owner read the same evidence twice on two dates. One date for
all six is deliberate too: the set is re-read in one sitting, which is what "the refusal set is
re-read rather than inherited" means.

**Four checks, and the second and third are the ones with teeth.**

1. `review_by` is a real `YYYY-MM-DD` date and is strictly in the FUTURE. This is the clock: on
   2026-12-03 this gate goes red and stays red until a human re-reads the licence.
2. `review_by` is at most `REVIEW_EVERY_DAYS` away. A date far enough out is a clock that never
   fires, so "a future date" alone is not enough -- `review_by = "2099-01-01"` satisfies check 1
   forever. This is 17-risks.md rule 4's `review_by - reviewed_at <= review_every_days` with
   *now* standing in for `reviewed_at`, because a tombstone card has no `reviewed_at` key: the
   `[tombstone]` table's legal keys are `reason`, `replaced_by` and `review_by` and nothing else
   (04 section 7.5). The substitution only ever tightens as the date approaches, so it never
   fails a card it once passed.
3. The roster matches 04 section 10.4. A tombstone missing is a vetoed id resolving to "unknown
   driver" (DR22's whole point); a tombstone added is a licence decision, and adding one is a
   two-file change on purpose. `NOT_TOMBSTONED` is the same check from the other side: two repos
   were considered and declined because the objection is supply chain rather than licence, and
   "we considered it and declined" is a fact worth protecting from a well-meaning PR.
4. Every card carries a non-empty reason, exactly one licence seed, and either a `replaced_by`
   naming a real successor or a reason that says in as many words that there is none.

**Exit codes.** 0 the set is current, 1 a check is false, 2 the gate did not run (a bad
argument, or the directory is missing). 1 and 2 are distinguished because CI treats both as
failure and a human needs to know which.

Stdlib only, and it imports nothing first-party. That is the property that lets this gate run on
a tree whose dependencies are not installed, which is the same discipline `tools/gate_layers.py`
and `tools/gate_licences.py` hold to (02-architecture.md section 3.3). The cost is that this
file re-reads five keys the card grammar also reads; it does not re-implement the grammar, and
the test half is where `load_card()` has the last word.

Specified in 04-driver-system.md sections 7.5 and 10.4, 01-principles.md DR22, 17-risks.md R-L1
and section 1 rule 4, 11-repo-layout.md section 9.2 layer 6.
"""

from __future__ import annotations

import argparse
import datetime as dt
import re
import sys
import tomllib
from dataclasses import dataclass
from pathlib import Path

__all__ = [
    "AUTHORED_ON",
    "DATALAB_LICENCE_SEED",
    "DATALAB_TOMBSTONES",
    "EXIT_CLEAN",
    "EXIT_FAIL",
    "EXIT_NOT_RUN",
    "NOT_TOMBSTONED",
    "NO_REPLACEMENT",
    "REVIEW_EVERY_DAYS",
    "SEED_RE",
    "SHIPPED",
    "TOMBSTONES",
    "Finding",
    "Tombstone",
    "audit",
    "load_tombstones",
    "main",
    "seeds",
    "today",
]

REPO = Path(__file__).resolve().parents[1]
"""The workspace root. `tools/` sits directly under it, so one `parents` hop, never a search."""

_CORE = REPO / "packages" / "omniweave-core" / "src" / "omniweave_core"
TOMBSTONES = _CORE / "drivers" / "tombstones"
"""The shipped refusal set. It is PACKAGE DATA, not a module: there is no `__init__.py` here and
`omniweave_core/drivers/__init__.py` stays docstring-only, so nothing imports a tombstone --
`Catalog.build()` reads these files at step 5 the same way it reads any other card."""

EXIT_CLEAN = 0
EXIT_FAIL = 1
EXIT_NOT_RUN = 2

REVIEW_EVERY_DAYS = 90
"""The licence owner's review cadence, transcribed from 17-risks.md section 1's `[register]
review_every_days = 90`. A tombstone is R-L1's second mitigation and R-L1's owner is the
`licence` role, so the refusal set is re-read on the cycle that already exists rather than on a
new one. It bounds `review_by` from ABOVE: a date further out than this is a clock that never
fires, which is the failure mode a `review_by` exists to prevent."""

AUTHORED_ON = dt.date(2026, 9, 6)
"""The day this set was written. Recorded because check 1 -- "`review_by` is a future date" -- is
a statement about AUTHORING time, and a card authored with an already-elapsed date would
otherwise be indistinguishable from a card that simply expired. It is not the anchor for check
2: see the module docstring."""

SHIPPED: dict[str, str | None] = {
    "derive.code.jcodemunch": None,
    "parse.doc.omniparse": "parse.office.anydoc",
    "parse.fields.lift": None,
    "parse.page.hunyuan": "parse.page.olmocr",
    "parse.page.marker": "parse.page.olmocr",
    "parse.page.surya": "parse.page.olmocr",
}
"""The six shipped tombstones and their replacements, transcribed from 04-driver-system.md
section 10.4's table. `None` is 10.4's *none* -- `parse.fields.lift` and
`derive.code.jcodemunch` have no successor and that is a finding, not a gap: nothing in the
roster does schema-guided field extraction, and naming a replacement that does not exist would
be worse than naming none."""

NOT_TOMBSTONED = {
    "Unlimited-OCR": (
        "MIT code, weights not in tree, and the install instruction is a 12.4 MB unsigned "
        "prebuilt sglang wheel from a dev commit. The objection is SUPPLY CHAIN, and a "
        "tombstone is a licence instrument"
    ),
    "Ollama-OCR": (
        "MIT, abandoned, unpinned, AGPL PyMuPDF transitively. Same objection, same instrument"
    ),
    "parse.pdf.pymupdf": (
        "AGPL-3.0 CODE computes `restricted`, which an operator running internally may "
        "knowingly accept. Tombstoning it would remove a decision that is theirs to make -- "
        "which is the whole reason `restricted` and `forbidden` are different tiers"
    ),
}
"""Three ids that were considered for a tombstone and declined, with the reason (04
section 7.5's closing paragraph and section 10.4's closing paragraph). A tombstone here would be
a silent policy change, so the gate fails on one. Neither of the first two was ever shipped, so
there is nothing to retire; both are refused by `require_lock`, by G3 and by
`[licence] allow_tiers` when their transitive AGPL surfaces."""

DATALAB_TOMBSTONES = ("parse.fields.lift", "parse.page.marker", "parse.page.surya")
"""The three whose licence seed must be ONE value. `md5sum marker/MODEL_LICENSE
surya/MODEL_LICENSE lift/MODEL_LICENSE` returns one digest three times (04 section 10.4), and
that byte-identity is why the seed set is hash-keyed rather than id-keyed: three distributions,
three driver ids, one licence file. If a well-meaning edit gave them three different digests the
mechanism would still look correct and would no longer survive a rename."""

DATALAB_LICENCE_SEED = "unresolved:md5=e1f69b64dee2f1641a9b1ab12adf24d6"
"""The one value those three carry. It is an UNRESOLVED seed and that is a deliberate, reported
state rather than a placeholder: the sha256 of `marker/MODEL_LICENSE` cannot be computed here,
because 11-repo-layout.md section 9.2 layer 1 is "it is not in the repository" and omniweave
will never vendor it. The plan prints the file's md5 and elides its sha256 (`licence_sha256 =
"sha256:..."`), so the marker carries the digest the plan does print, cannot be mistaken for a
sha256, and cannot false-positive against any real card. Resolving it upstream is W3.3's, with
`compute_tier()`."""

SEED_RE = re.compile(r"^(?:sha256:[0-9a-f]{64}|unresolved:\S.*)$")
"""A licence seed is either a real `sha256:<64 hex>` or an explicitly-marked `unresolved:`
value naming what has to be fetched. The empty string is neither, and that is the point: a
seed set built by unioning `[licence.code].licence_sha256` and
`[licence.weights].licence_sha256` over these files would, if an empty string reached it, match
every card that omits its own digest -- turning `compute_tier()`'s narrowest check into a
blanket `forbidden`. This gate refuses to ship a card that could put one there."""

NO_REPLACEMENT = "There is no replacement."
"""The sentence a tombstone with no successor must contain, verbatim.

The card grammar spells "no replacement" as an ABSENT `replaced_by` key, and an absent key is
also how a card would spell "nobody wrote one down" -- `card.py`'s `_tombstone_replacement()`
resolves that with "`replaced_by` may be omitted only when there is no successor; then `reason`
says so". This constant is what makes "then `reason` says so" checkable. Adding a `replaced_by =
"none"` spelling was the alternative and is worse: `_tombstone_replacement()` requires a
`DriverId`, so `"none"` would be `CARD_INVALID`, and widening the grammar to admit a magic
string would put a second spelling of absence into a type that already has one."""


@dataclass(frozen=True, slots=True)
class Tombstone:
    """The five keys this gate reads. Deliberately NOT the card grammar.

    `omniweave_core.drivers.card.Tombstone` is the real type and the test half loads every one
    of these files through it. This record exists because a gate that imported `omniweave_core`
    to inspect it would need `omniweave_core` installed, and a licence gate has to run on a tree
    whose dependencies are not installed (02-architecture.md section 3.3).
    """

    path: Path
    id: str
    reason: str
    replaced_by: str | None
    review_by: str
    seeds: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class Finding:
    """One failed check. `subject` is the id or file; `detail` is what a human has to go do."""

    check: str
    subject: str
    detail: str


def today() -> dt.date:
    """The wall clock, UTC. The one impure call in this file, and it is the gate's whole point."""
    return dt.datetime.now(tz=dt.UTC).date()


def seeds(doc: dict[str, object]) -> tuple[str, ...]:
    """Every non-empty `licence_sha256` in a card, code side and weights side.

    04 section 7.5: `compute_tier()` returns `forbidden` for a card whose
    `[licence.code].licence_sha256` **or** `[licence.weights].licence_sha256` matches a shipped
    tombstone's. Both sides are read because two of the six -- `derive.code.jcodemunch` and
    `parse.doc.omniparse` -- ship no weights at all, so 11-repo-layout.md:2503's "each carrying
    ... a `[licence.weights].licence_sha256`" is true of four of the six and not of all six.
    """
    licence = doc.get("licence")
    if not isinstance(licence, dict):
        return ()
    found: list[str] = []
    for side in ("code", "weights"):
        table = licence.get(side)
        if isinstance(table, dict):
            value = table.get("licence_sha256")
            if isinstance(value, str) and value:
                found.append(value)
    return tuple(found)


def _required_table(doc: dict[str, object], name: str, path: Path) -> dict[str, object]:
    """`[driver]` and `[tombstone]`, or a `ValueError` naming the file that lacks one.

    A `ValueError` and not a `TypeError`: the file is readable TOML and its VALUE is wrong, which
    is the same distinction `main()` draws between exit 1 and exit 2.
    """
    value = doc.get(name)
    if isinstance(value, dict):
        return value
    raise ValueError(f"{path}: [{name}] is required and must be a table")


def load_tombstones(root: Path) -> tuple[Tombstone, ...]:
    """Every `*.toml` under `root`, in sorted order. Raises `OSError` when `root` is not there."""
    if not root.is_dir():
        raise NotADirectoryError(root)
    loaded: list[Tombstone] = []
    for path in sorted(root.glob("*.toml")):
        doc = tomllib.loads(path.read_text(encoding="utf-8"))
        driver = _required_table(doc, "driver", path)
        table = _required_table(doc, "tombstone", path)
        replaced = table.get("replaced_by")
        loaded.append(
            Tombstone(
                path=path,
                id=str(driver.get("id", "")),
                reason=str(table.get("reason", "")),
                replaced_by=str(replaced) if isinstance(replaced, str) else None,
                review_by=str(table.get("review_by", "")),
                seeds=seeds(doc),
            )
        )
    return tuple(loaded)


def _check_clock(card: Tombstone, now: dt.date) -> list[Finding]:
    """Checks 1 and 2: a real date, strictly future, and no further out than the cadence."""
    try:
        due = dt.date.fromisoformat(card.review_by)
    except ValueError:
        return [
            Finding(
                "review_by",
                card.id,
                f"{card.review_by!r} is not a YYYY-MM-DD date; a tombstone without a readable "
                f"clock is a refusal that ossifies",
            )
        ]
    found: list[Finding] = []
    if due <= now:
        found.append(
            Finding(
                "review_by",
                card.id,
                f"review_by {due.isoformat()} is not in the future as of {now.isoformat()}. "
                f"Re-READ the licence -- do not re-date the card -- then set a new review_by no "
                f"more than {REVIEW_EVERY_DAYS} days out",
            )
        )
    if due > now + dt.timedelta(days=REVIEW_EVERY_DAYS):
        found.append(
            Finding(
                "review_by",
                card.id,
                f"review_by {due.isoformat()} is more than {REVIEW_EVERY_DAYS} days after "
                f"{now.isoformat()}; a clock that far out never fires (17-risks.md section 1 "
                f"rule 4)",
            )
        )
    if due <= AUTHORED_ON:
        found.append(
            Finding(
                "review_by",
                card.id,
                f"review_by {due.isoformat()} was not a future date when this set was authored "
                f"on {AUTHORED_ON.isoformat()}",
            )
        )
    return found


def _check_card(card: Tombstone) -> list[Finding]:
    """Check 4: a non-empty reason, one well-formed seed, and a stated replacement or none."""
    found: list[Finding] = []
    if not card.reason.strip():
        found.append(
            Finding(
                "reason",
                card.id,
                "the reason is empty. DR22 exists so a vetoed id resolves to a QUOTED REASON "
                "and a named replacement, never to 'unknown driver'",
            )
        )
    if card.replaced_by is None and NO_REPLACEMENT not in card.reason:
        found.append(
            Finding(
                "replaced_by",
                card.id,
                f"no replaced_by, and the reason does not contain {NO_REPLACEMENT!r}. An absent "
                f"key cannot tell 'there is no successor' from 'nobody wrote one down', so the "
                f"reason has to say which",
            )
        )
    if not card.seeds:
        found.append(
            Finding(
                "licence_sha256",
                card.id,
                "no licence seed on either [licence.code] or [licence.weights]. The tombstone's "
                "second job is the known-bad-licence set, which is hash-keyed so it survives a "
                "rename (04 section 7.5)",
            )
        )
    for seed in card.seeds:
        if SEED_RE.match(seed) is None:
            found.append(
                Finding(
                    "licence_sha256",
                    card.id,
                    f"{seed!r} is neither a sha256:<64 hex> digest nor an explicit "
                    f"'unresolved:<what to fetch>' marker",
                )
            )
    if card.path.stem != card.id:
        found.append(
            Finding(
                "filename",
                card.id,
                f"lives in {card.path.name}; a tombstone file is named for the id it retires, so "
                f"a reader looking for a refusal finds it without opening six files",
            )
        )
    return found


def _check_roster(cards: tuple[Tombstone, ...]) -> list[Finding]:
    """Check 3: the directory is exactly 04 section 10.4's table, and no more."""
    found: list[Finding] = []
    by_id = {card.id: card for card in cards}
    if len(by_id) != len(cards):
        found.append(Finding("roster", "*", "two tombstones share one id"))
    for missing in sorted(set(SHIPPED) - set(by_id)):
        found.append(
            Finding(
                "roster",
                missing,
                "04 section 10.4 ships a tombstone for this id and there is none. A vetoed id "
                "without a tombstone resolves to 'unknown driver', which is what DR22 forbids",
            )
        )
    for extra in sorted(set(by_id) - set(SHIPPED)):
        found.append(
            Finding(
                "roster",
                extra,
                "is tombstoned and is not in 04 section 10.4's table. Adding a refusal is a "
                "licence decision: amend the plan and SHIPPED together, in one review",
            )
        )
    for name, why in sorted(NOT_TOMBSTONED.items()):
        if name in by_id:
            found.append(Finding("declined", name, f"was considered and DECLINED: {why}"))
    for card in cards:
        expected = SHIPPED.get(card.id, ...)
        if expected is not ... and card.replaced_by != expected:
            found.append(
                Finding(
                    "replaced_by",
                    card.id,
                    f"names {card.replaced_by!r}; 04 section 10.4 says "
                    f"{expected if expected is not None else 'none'}",
                )
            )
    return found


def _check_datalab(cards: tuple[Tombstone, ...]) -> list[Finding]:
    """The byte-identical-file property, asserted as data rather than remembered as trivia."""
    found: list[Finding] = []
    by_id = {card.id: card for card in cards}
    present = [by_id[name] for name in DATALAB_TOMBSTONES if name in by_id]
    for card in present:
        if DATALAB_LICENCE_SEED not in card.seeds:
            found.append(
                Finding(
                    "datalab",
                    card.id,
                    f"carries {list(card.seeds)} and not {DATALAB_LICENCE_SEED!r}. marker, surya "
                    f"and lift share ONE MODEL_LICENSE file; three different digests would look "
                    f"correct and would stop surviving a rename",
                )
            )
    others = [
        card
        for card in cards
        if card.id not in DATALAB_TOMBSTONES and DATALAB_LICENCE_SEED in card.seeds
    ]
    for card in others:
        found.append(
            Finding(
                "datalab",
                card.id,
                "restates the Datalab licence seed. It is one file: seed it once per "
                "distribution that ships it, and state a transitive encumbrance in the reason",
            )
        )
    return found


def audit(root: Path, now: dt.date) -> list[Finding]:
    """Every check, over `root`, as of `now`. Pure but for the file reads -- `now` is injected."""
    cards = load_tombstones(root)
    found = _check_roster(cards)
    found += _check_datalab(cards)
    for card in cards:
        found += _check_clock(card, now)
        found += _check_card(card)
    return found


def _emit(line: str) -> None:
    """The gate's one write. `print` is banned repo-wide by ruff `T20`; this needs no waiver."""
    sys.stdout.write(line + "\n")


def main(argv: list[str] | None = None) -> int:
    """Run the clock over the shipped set. 0 current, 1 a check is false, 2 the gate did not run."""
    parser = argparse.ArgumentParser(
        description="The tombstone clock -- CI fails a tombstone past its review_by."
    )
    parser.parse_args(argv)
    now = today()
    try:
        cards = load_tombstones(TOMBSTONES)
    except (OSError, ValueError, tomllib.TOMLDecodeError) as exc:
        _emit(f"tombstones DID NOT RUN  {exc}")
        return EXIT_NOT_RUN
    findings = audit(TOMBSTONES, now)

    unresolved = sorted(
        {seed for card in cards for seed in card.seeds if seed.startswith("unresolved:")}
    )
    resolved = sorted({seed for card in cards for seed in card.seeds if seed.startswith("sha256:")})
    _emit(f"tombstones  {TOMBSTONES.relative_to(REPO).as_posix()}  as of {now.isoformat()}")
    for card in cards:
        due = card.review_by
        left = ""
        try:
            left = f"{(dt.date.fromisoformat(due) - now).days:>4} days left"
        except ValueError:
            left = "  unreadable"
        _emit(f"  {card.id:<26} {due}  {left}   -> {card.replaced_by or 'no replacement'}")
    _emit(f"  seed set    {len(resolved)} resolved, {len(unresolved)} unresolved")
    for seed in unresolved:
        _emit(f"    unresolved  {seed}")
    _emit("")

    if findings:
        for finding in findings:
            _emit(f"FAIL  {finding.check:<15} {finding.subject}")
            _emit(f"      {finding.detail}")
        _emit(f"\ntombstones FAIL  {len(findings)} finding(s) over {len(cards)} tombstone(s).")
        return EXIT_FAIL
    _emit(
        f"tombstones ok  {len(cards)} refusals, every review_by inside "
        f"{REVIEW_EVERY_DAYS} days, roster matches 04-driver-system.md section 10.4."
    )
    return EXIT_CLEAN


if __name__ == "__main__":
    raise SystemExit(main())
