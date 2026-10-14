"""`omniweave_conform.bless`: the flag, `BLESS.log` and the reviewer rule. D820."""

from __future__ import annotations

import os

import pytest
from omniweave_conform.bless import (
    BLESS_ENV,
    BlessPlan,
    BlessRow,
    append_only,
    blessing,
    covers,
    parse_log,
    plan,
    schema_bump_only,
)
from omniweave_conform.churn import CHURN_SYMBOL, Churn
from omniweave_core.errors import QualityError

ON = {BLESS_ENV: "1"}
REASON = "anydoc 0.2.5 fixes w:instrText field-code text"
GLOB = "fixtures/goldens/core@2026.09/parse.office.anydoc@3/*"


def _churn(**classes: int) -> dict[str, Churn]:
    out = {}
    for cls, n in classes.items():
        for i in range(n):
            path = f"fixtures/goldens/core@2026.09/parse.office.anydoc@3/{cls}-{i}.pages"
            out[path] = Churn(cls, (), ())  # type: ignore[arg-type]
    return out


def _plan(churn: dict[str, Churn], **over: object) -> BlessPlan:
    kw: dict[str, object] = {
        "env": ON,
        "date": "2026-10-14",
        "author": "team@particle6.com",
        "glob": GLOB,
        "reason": REASON,
    }
    kw.update(over)
    return plan(churn, **kw)  # type: ignore[arg-type]


def _row(**over: object) -> BlessRow:
    kw: dict[str, object] = {
        "date": "2026-10-14",
        "author": "team@particle6.com",
        "glob": GLOB,
        "counts": {"incidental": 39, "structural": 2, "unexplained": 0},
        "reason": REASON,
    }
    kw.update(over)
    return BlessRow(**kw)  # type: ignore[arg-type]


# --- requirement 1 ---------------------------------------------------------------------------


def test_bless_flag_is_off() -> None:
    """13:799, docling's `tests/test_data_gen_flag.py` adopted whole: a suite that ran with the
    flag exported could bless its own goldens, so a run that has it fails here."""
    assert os.environ.get(BLESS_ENV) != "1"


def test_blessing_reads_the_mapping_it_is_given() -> None:
    assert blessing(ON)
    assert not blessing({})
    assert not blessing({BLESS_ENV: "true"})
    assert not blessing({BLESS_ENV: "0"})


def test_a_bless_without_the_flag_is_refused() -> None:
    with pytest.raises(QualityError, match=r"OMNIWEAVE_BLESS=1 is not in the environment"):
        _plan(_churn(incidental=1), env={})


# --- requirements 3 and 4 --------------------------------------------------------------------


def test_the_plans_worked_example_needs_one_reviewer() -> None:
    """13:789-794: 39 incidental and 2 structural, 2/41 = 4.9%."""
    got = _plan(_churn(incidental=39, structural=2))
    assert got.second_reviewer is False
    assert (got.structural, got.touched) == (2, 41)
    assert got.row.counts == {"incidental": 39, "structural": 2, "unexplained": 0}


def test_the_plans_nine_of_forty_one_needs_two() -> None:
    """13:808: *"9 `structural` changes out of 41 is two"*, at 22%."""
    assert _plan(_churn(incidental=32, structural=9)).second_reviewer is True


def test_the_second_reviewer_is_strictly_above_twenty_percent_of_what_changed() -> None:
    assert _plan(_churn(incidental=8, structural=2)).second_reviewer is False
    assert _plan(_churn(incidental=7, structural=3)).second_reviewer is True
    with_still = {**_churn(incidental=8, structural=2), **_churn(unchanged=100)}
    assert _plan(with_still).touched == 10
    assert _plan(_churn(incidental=400)).second_reviewer is False


def test_unexplained_has_no_override() -> None:
    churn = {**_churn(incidental=5), **_churn(unexplained=2)}
    with pytest.raises(QualityError, match=r"2 golden file\(s\) changed unexplained") as got:
        _plan(churn)
    assert got.value.code() == CHURN_SYMBOL
    assert got.value.fix.startswith("ow eval golden --explain fixtures/goldens/")


def test_nothing_to_bless_is_refused() -> None:
    with pytest.raises(QualityError, match="nothing to bless"):
        _plan(_churn(unchanged=3))


# --- requirement 2: the row ------------------------------------------------------------------


def test_a_row_is_five_tab_separated_fields() -> None:
    assert _row().line() == (
        f"2026-10-14\tteam@particle6.com\t{GLOB}\t"
        f"incidental=39,structural=2,unexplained=0\t{REASON}\n"
    )


@pytest.mark.parametrize(
    ("over", "match"),
    [
        ({"reason": "fix things"}, "at least 20 characters"),
        ({"reason": "   " + "x" * 19 + "   "}, "at least 20 characters"),
        ({"reason": REASON + "\tmore"}, "tab or a line break"),
        ({"glob": "a\nb"}, "tab or a line break"),
        ({"date": "14/10/2026"}, "YYYY-MM-DD"),
        ({"author": "team"}, "not an email"),
        ({"glob": " "}, "glob is empty"),
        ({"counts": {"incidental": 1}}, "three classes"),
        ({"counts": {"incidental": -1, "structural": 0, "unexplained": 0}}, "three classes"),
    ],
)
def test_a_malformed_row_is_refused(over: dict[str, object], match: str) -> None:
    with pytest.raises(QualityError, match=match):
        _row(**over)


def test_a_planned_row_parses_back() -> None:
    row = _plan(_churn(incidental=3, structural=1)).row
    assert parse_log(row.line()) == (row,)


def test_the_log_is_whole_lines_of_five_fields() -> None:
    with pytest.raises(QualityError, match="does not end in LF"):
        parse_log(_row().line().rstrip("\n"))
    with pytest.raises(QualityError, match=r"BLESS\.log:1 has 4 fields"):
        parse_log("2026-10-14\ta@b\tg\tincidental=1,structural=0,unexplained=0\n")
    with pytest.raises(QualityError, match=r"BLESS\.log:2 counts"):
        parse_log(_row().line() + _row().line().replace("structural=2", "structural=two"))
    assert parse_log("") == ()


def test_the_log_is_append_only() -> None:
    old = _row().line()
    added = _row(date="2026-10-15").line()
    assert append_only(old, old + added) == (_row(date="2026-10-15"),)
    with pytest.raises(QualityError, match="rewritten, not appended"):
        append_only(old, _row(reason=REASON + ", reworded").line() + added)
    assert append_only(old, old) == ()


# --- Q-G3 and the schema bump ----------------------------------------------------------------


def test_every_changed_reduction_needs_a_new_row() -> None:
    changed = [
        "fixtures/goldens/core@2026.09/parse.office.anydoc@3/a.shape",
        "fixtures\\goldens\\core@2026.09\\parse.office.anydoc@3\\a.pages",
        "fixtures/goldens/core@2026.09/parse.pdf.pdfium@1/b.shape",
    ]
    got = covers(changed, [_row()])
    assert got.unblessed == ("fixtures/goldens/core@2026.09/parse.pdf.pdfium@1/b.shape",)
    assert got.idle == ()
    idle = _row(glob="fixtures/goldens/other/*")
    assert covers(changed[:1], [_row(), idle]).idle == (idle,)


def test_a_schema_bump_is_the_header_field_alone() -> None:
    old = "owshape/1  corpus=c  doc=k  driver=d@1  schema_v=1\nblocks.total 5\n"
    assert schema_bump_only(old, old.replace("schema_v=1", "schema_v=2"))
    assert not schema_bump_only(old, old.replace("schema_v=1", "schema_v=2").replace("5", "6"))
    assert not schema_bump_only(old, old)
    body_mention = old + "achieved.note schema_v=1\n"
    assert not schema_bump_only(body_mention, body_mention.replace("schema_v=1", "schema_v=2"))
