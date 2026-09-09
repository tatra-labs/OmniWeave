"""`enum_val` in the migrations equals `omniweave_core.model.enums`, in BOTH directions.

16-roadmap.md:415 (W2.2) asks for "`enum_val` generation with two-way CI parity", and
03-document-model.md:2754-2757 gives the model it serves: a migration "regenerates `enum_val` from
the Python enums with CI asserting parity in both directions and the append-only assertion of
section 2.1", and generated enforcers are emitted from the same source "so there is **one truth and
two enforcers**".

This file is that assertion. The truth is `enum_val_rows()`; the SQL is the second enforcer; and
parity is what stops the enforcer becoming a second truth. Neither direction alone is enough:

* SQL -> Python catches a hand-edited row, a typo'd name, a duplicated ordinal.
* Python -> SQL catches an enum member added and never seeded -- which is the failure that
  actually happened here. `0001_init.sql` seeded L2's nine domains, `0002_graph.sql` seeded none,
  and `enum_val` held **nine of the fifteen** closed domains with nothing complaining, because
  every test in the suite compared only what was present against what was expected to be present.

WHY THIS APPLIES THE MIGRATIONS, and why `import sqlite3` is exempted here. INV-17 bans the
import outside `omniweave_core/store/` and the sibling `test_migration_0002_0003.py` declines it
on exactly those grounds, asserting over file bytes instead. This file needs the applied database,
because parity is a property of the ROWS `enum_val` ends up holding after all four migrations --
which is not derivable from any one file's text, since 0001 seeds nine domains and 0002 seeds six.
`test_migration_0001.py` takes the same exemption for the same reason (`import sqlite3  # noqa:
TID251`, its line 42). The ban's subject is production code reaching for a second database
connection; a test that opens `:memory:` to check what the DDL produced is the instrument, not a
violation.

WHY IT ALSO READS THE .sql FILES. Both, in fact: the ordinal parity is checked
against a real applied database (so a `CHECK` constraint or trigger that rejects a seed row is
caught), and the append-only assertion is checked against the file text (so a REORDERED literal is
caught even when the applied result is identical, which it would be, since `enum_val` is keyed on
`(domain, ord)` and a re-ordered INSERT list produces the same table).

Specified in 03-document-model.md sections 2.1 and 15.3, and 16-roadmap.md section 5 W2.2.
"""

from __future__ import annotations

import re
import sqlite3  # noqa: TID251 -- see WHY THIS APPLIES THE MIGRATIONS, in the docstring.
from pathlib import Path

import pytest
from omniweave_core.model.enums import ENUM_DOMAINS, enum_val_rows

MIGRATIONS = Path(__file__).resolve().parents[4] / "schema" / "migrations"

# 03-document-model.md:2311's list, verbatim and in its order. Transcribed rather than taken from
# ENUM_DOMAINS, because a test that reads its expectation out of the module it checks asserts only
# self-agreement -- the same reason tools/gate_coldstart.py does not import its own ceilings.
CLOSED_DOMAINS: tuple[str, ...] = (
    "kind",
    "layer",
    "trust",
    "method",
    "quote",
    "page_kind",
    "table_kind",
    "rel_kind",
    "origin_span_kind",
    "lane",
    "akind",
    "alias_kind",
    "claim_status",
    "taint",
    "precision",
)

_SEED = re.compile(r"\('(?P<domain>[a-z_]+)',\s*(?P<ord>\d+),\s*'(?P<name>[a-z_0-9]+)'\)")


@pytest.fixture(scope="module")
def applied() -> sqlite3.Connection:
    """The four migrations applied in numeric order onto an empty database.

    Numeric order matters and is not cosmetic: 11-repo-layout.md:1188 fixes it because L4's indexes
    and foreign keys reference L3's tables. `sorted()` over four four-digit prefixes is that order.
    """
    con = sqlite3.connect(":memory:")
    con.execute("PRAGMA foreign_keys = ON")
    for path in sorted(MIGRATIONS.glob("[0-9][0-9][0-9][0-9]_*.sql")):
        con.executescript(path.read_text(encoding="utf-8"))
    return con


def _seeded_text() -> list[tuple[str, int, str]]:
    """Every `enum_val` seed triple in the migration files, in the order they appear on disk."""
    found: list[tuple[str, int, str]] = []
    for path in sorted(MIGRATIONS.glob("[0-9][0-9][0-9][0-9]_*.sql")):
        for block in re.split(r"INSERT INTO enum_val", path.read_text(encoding="utf-8"))[1:]:
            statement = block.split(";", 1)[0]
            found += [
                (m.group("domain"), int(m.group("ord")), m.group("name"))
                for m in _SEED.finditer(statement)
            ]
    return found


# ---------------------------------------------------------------------------------------------
# The two directions
# ---------------------------------------------------------------------------------------------


def test_python_to_sql_every_declared_row_is_seeded(applied: sqlite3.Connection) -> None:
    """Direction 1. An enum member with no `enum_val` row is a value the store cannot name."""
    stored = set(applied.execute("SELECT domain, ord, name FROM enum_val"))
    missing = sorted(set(enum_val_rows()) - stored)
    assert missing == [], f"declared in Python and absent from enum_val: {missing}"


def test_sql_to_python_every_seeded_row_is_declared(applied: sqlite3.Connection) -> None:
    """Direction 2. A row in `enum_val` that no enum declares is a hand edit."""
    stored = set(applied.execute("SELECT domain, ord, name FROM enum_val"))
    extra = sorted(stored - set(enum_val_rows()))
    assert extra == [], f"seeded in SQL and declared nowhere in Python: {extra}"


def test_the_row_counts_agree_exactly(applied: sqlite3.Connection) -> None:
    """Set equality above would hold with a duplicate on one side; a count catches that."""
    stored = applied.execute("SELECT count(*) FROM enum_val").fetchone()[0]
    assert stored == len(enum_val_rows())
    assert len(set(enum_val_rows())) == len(enum_val_rows()), "enum_val_rows() has a duplicate"


# ---------------------------------------------------------------------------------------------
# The fifteen, and the one that must not be there
# ---------------------------------------------------------------------------------------------


def test_exactly_the_fifteen_closed_domains_are_seeded(applied: sqlite3.Connection) -> None:
    """03-document-model.md:2311 enumerates fifteen. Nine were seeded before this test existed."""
    stored = {row[0] for row in applied.execute("SELECT DISTINCT domain FROM enum_val")}
    assert stored == set(CLOSED_DOMAINS), (
        f"missing {sorted(set(CLOSED_DOMAINS) - stored)}, "
        f"unexpected {sorted(stored - set(CLOSED_DOMAINS))}"
    )
    assert set(ENUM_DOMAINS) == set(CLOSED_DOMAINS)


def test_format_is_not_an_enum_val_domain(applied: sqlite3.Connection) -> None:
    """`format` is free text over a COMPUTED domain and must never appear here.

    Five sites say so -- charter.md:942 (the closed-domain list), charter.md:7948 ("`enum_val` holds
    the closed domains only"), charter erratum D26 at charter.md:8746 ("which do not include
    `format`"), 03-document-model.md:2311 and adr/0012:197. Two sentences in
    05-ingest-and-routing.md (:633 and :2074) say the opposite and are defective; the ruling is
    recorded in _plan/_notes/build-defects.md as D10.

    The reason is mechanical, not stylistic: `unit.format`'s domain is core's 48 tokens UNION the
    tokens of every enabled driver card, and `enum_val.ord` is the append-only STORED value. A
    domain a third-party card can extend would mint an ordinal on enable, so the same `.owdoc`
    would disagree with itself depending on which drivers were installed -- an INV-10
    (byte-exactness) break and a portability break at once.
    """
    rows = applied.execute("SELECT count(*) FROM enum_val WHERE domain = 'format'").fetchone()[0]
    assert rows == 0
    assert "format" not in ENUM_DOMAINS


# ---------------------------------------------------------------------------------------------
# Section 2.1: the ordinal IS the stored value, and it is append-only
# ---------------------------------------------------------------------------------------------


def test_each_domains_ordinals_are_unique_within_the_domain(applied: sqlite3.Connection) -> None:
    """`PRIMARY KEY (domain, ord)` enforces this in the database; asserted so a failure names it."""
    clashes = applied.execute(
        "SELECT domain, ord, count(*) FROM enum_val GROUP BY domain, ord HAVING count(*) > 1"
    ).fetchall()
    assert clashes == []


def test_an_ordered_int_enums_ord_is_the_members_own_integer() -> None:
    """`trust`, `quote` and `taint` carry meaning in the integer, so `ord` must BE the integer.

    For `quote` this is the property 16-roadmap.md W2.1's estimation basis singles out as one of
    the two tests that are not transcription: `Quote.SYNTHETIC < Quote.VERBATIM`, weakest lowest.
    A reversed ordering would invert every `MIN()` in the retrieval stack silently, and
    `segment.quote_min` is defined as the weakest member of a mixed segment.
    """
    for domain in ("trust", "quote", "taint"):
        for ordinal, name in ((o, n) for d, o, n in enum_val_rows() if d == domain):
            member = ENUM_DOMAINS[domain][name.upper()]
            assert int(member) == ordinal, f"{domain}.{name} stores {ordinal}, is {int(member)}"


def test_taints_ordinals_are_flag_bits_and_are_deliberately_not_dense() -> None:
    """The one domain whose `ord` sequence has gaps, asserted so nobody 'fixes' it.

    `Taint` is an `IntFlag`: 0, 1, 2, 4, 8, 16. A reader inferring position from `ord` would be
    wrong here and only here, and renumbering it densely would silently reinterpret every stored
    `taint` column in every existing store.
    """
    ordinals = [o for d, o, _ in enum_val_rows() if d == "taint"]
    assert ordinals == [0, 1, 2, 4, 8, 16]
    assert ordinals != list(range(len(ordinals))), "taint must not be dense"


def test_a_str_enums_ordinals_are_dense_from_zero() -> None:
    """Declaration order, contiguous. A gap in a StrEnum domain is an unrecorded removal."""
    for domain in CLOSED_DOMAINS:
        if domain in ("trust", "quote", "taint"):
            continue
        ordinals = sorted(o for d, o, _ in enum_val_rows() if d == domain)
        assert ordinals == list(range(len(ordinals))), f"{domain} ordinals are {ordinals}"


def test_the_seed_literals_are_written_in_ordinal_order() -> None:
    """Read off the FILE TEXT, because the applied database cannot show this.

    `enum_val` is keyed on `(domain, ord)`, so a re-ordered INSERT list produces a byte-identical
    table and every assertion above still passes. The order in the file is nonetheless the thing a
    reviewer reads to check the append-only rule of section 2.1: an ordinal inserted in the middle
    is what that rule forbids, and in a sorted table it is invisible.
    """
    seen: dict[str, list[int]] = {}
    for domain, ordinal, _ in _seeded_text():
        seen.setdefault(domain, []).append(ordinal)
    assert seen, "no enum_val seed literals found -- this test would be vacuous"
    for domain, ordinals in seen.items():
        assert ordinals == sorted(ordinals), f"{domain} seeds are out of ordinal order: {ordinals}"


def test_every_domain_is_seeded_in_exactly_one_migration_file() -> None:
    """One domain, one home. Two files seeding `kind` would be two truths and a merge hazard."""
    homes: dict[str, set[str]] = {}
    for path in sorted(MIGRATIONS.glob("[0-9][0-9][0-9][0-9]_*.sql")):
        for block in re.split(r"INSERT INTO enum_val", path.read_text(encoding="utf-8"))[1:]:
            for match in _SEED.finditer(block.split(";", 1)[0]):
                homes.setdefault(match.group("domain"), set()).add(path.name)
    split = {d: sorted(f) for d, f in homes.items() if len(f) > 1}
    assert split == {}, f"seeded in more than one migration: {split}"
    assert set(homes) == set(CLOSED_DOMAINS)
