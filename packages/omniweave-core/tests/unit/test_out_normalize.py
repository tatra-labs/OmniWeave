"""`out.normalize.normalize()`: each `normalize` row's normalizer, through the splice (D768).

The bundles are owtext's, whose one `normalize` row is `attr.class.upper`: an upper-case class name
is folded by `lower_ascii`. A report, where a test needs one, is the one `check()` writes.
"""

from __future__ import annotations

import tomllib
from pathlib import Path
from typing import Any

import pytest
from omniweave_conform.suites.target.owtext.driver import HERE, OwTextCompiler
from omniweave_conform.suites.target.owtext.normalizers import lower_ascii
from omniweave_core.errors import NotFoundError, TargetError
from omniweave_core.out.compile import check
from omniweave_core.out.constructs import ConstructTable
from omniweave_core.out.normalize import Normalized, normalize

NORMALIZERS = {"lower_ascii": lower_ascii}
TABLE = ConstructTable.load(HERE / "constructs.toml", NORMALIZERS)
CARRIER = OwTextCompiler().carrier


def _job(tmp_path: Path, table: ConstructTable = TABLE, **units: str) -> Path:
    il = tmp_path / "il"
    il.mkdir()
    rows = "".join(
        f'\n[[unit]]\nid = "{unit}"\nord = {n}\nfile = "{unit}.html"\n'
        for n, unit in enumerate(units, start=1)
    )
    (il / "il.toml").write_text(
        f'schema = "omniweave.out-il/1"\nil = "owtext/1"\nconstructs_digest = "{table.digest()}"\n'
        + rows,
        encoding="utf-8",
    )
    for unit, text in units.items():
        (il / f"{unit}.html").write_text(text, encoding="utf-8", newline="")
    return tmp_path


def _text(job: Path, unit: str) -> str:
    return (job / "il" / f"{unit}.html").read_text(encoding="utf-8")


def _normalize(job: Path, **kwargs: Any) -> Normalized:
    return normalize(
        job,
        carrier=CARRIER,
        constructs=kwargs.pop("constructs", TABLE),
        normalizers=kwargs.pop("normalizers", NORMALIZERS),
        **kwargs,
    )


UPPER = '<section>\n  <p class="Lead Story">One.</p>\n  <p class="x">Two.</p>\n</section>\n'


# ---------------------------------------------------------------------------------------------
# Rulings 1 and 4: the value, rewritten in place
# ---------------------------------------------------------------------------------------------


def test_an_upper_case_class_is_folded_in_place_and_counted(tmp_path: Path) -> None:
    job = _job(tmp_path, u01=UPPER)
    done = _normalize(job)
    assert {u: dict(c) for u, c in done.changed.items()} == {"u01": {"attr.class.upper": 1}}
    assert done.written == ("u01.html",)
    assert _text(job, "u01") == UPPER.replace("Lead Story", "lead story")


def test_a_clean_bundle_writes_nothing(tmp_path: Path) -> None:
    job = _job(tmp_path, u01='<section>\n  <p class="lead">One.</p>\n</section>\n')
    before = (job / "il" / "u01.html").read_bytes()
    done = _normalize(job)
    assert (dict(done.changed), done.written) == ({}, ())
    assert (job / "il" / "u01.html").read_bytes() == before


def test_a_single_quoted_value_keeps_its_quote(tmp_path: Path) -> None:
    job = _job(tmp_path, u01="<section>\n  <p class='Lead'>One.</p>\n</section>\n")
    _normalize(job)
    assert "<p class='lead'>One.</p>" in _text(job, "u01")


def test_the_new_value_is_escaped_for_its_quote_and_reads_back(tmp_path: Path) -> None:
    job = _job(tmp_path, u01=UPPER)
    _normalize(job, normalizers={"lower_ascii": lambda _value: 'a&b"c'})
    assert '<p class="a&amp;b&quot;c">One.</p>' in _text(job, "u01")
    doc = CARRIER("il/u01.html", _text(job, "u01"))
    assert {n.attr("class") for n in doc.select("@class")} == {'a&b"c'}


def test_a_single_quoted_value_is_escaped_for_its_own_quote(tmp_path: Path) -> None:
    job = _job(tmp_path, u01="<section>\n  <p class='Lead'>One.</p>\n</section>\n")
    _normalize(job, normalizers={"lower_ascii": lambda _value: 'it\'s "so"'})
    assert "<p class='it&#39;s \"so\"'>One.</p>" in _text(job, "u01")
    doc = CARRIER("il/u01.html", _text(job, "u01"))
    assert {n.attr("class") for n in doc.select("@class")} == {'it\'s "so"'}


def test_an_attribute_named_inside_another_is_not_mistaken_for_it(tmp_path: Path) -> None:
    """The match is the attribute itself, never `data-class=` or a value that mentions it."""
    source = '<section>\n  <p data-class="Keep" title="class=X" class="Lead">One.</p>\n</section>\n'
    job = _job(tmp_path, u01=source)
    _normalize(job)
    assert _text(job, "u01") == source.replace('class="Lead"', 'class="lead"')


# ---------------------------------------------------------------------------------------------
# Rulings 2 and 3: the report, the construct and the unit
# ---------------------------------------------------------------------------------------------


def _checked(job: Path) -> None:
    check(job, OwTextCompiler(), target="owtext", constructs=TABLE, stage="early")


def test_a_current_report_names_the_rows_that_run(tmp_path: Path) -> None:
    job = _job(tmp_path, u01=UPPER)
    _checked(job)
    done = _normalize(job, stage="early")
    assert {u: dict(c) for u, c in done.changed.items()} == {"u01": {"attr.class.upper": 1}}


def test_a_report_older_than_the_bytes_is_refused(tmp_path: Path) -> None:
    job = _job(tmp_path, u01='<section>\n  <p class="lead">One.</p>\n</section>\n')
    _checked(job)
    unit = job / "il" / "u01.html"
    #  The bytes moved after the check, so the report must be refused rather than trusted.
    unit.write_text(UPPER, encoding="utf-8")
    with pytest.raises(TargetError, match="describes other bytes") as caught:
        _normalize(job, stage="early")
    assert caught.value.code() == "OW_TARGET_NORMALIZE_STALE"
    assert caught.value.fix == "ow out check --stage early"
    assert _text(job, "u01") == UPPER


def test_a_stage_with_no_report_is_refused(tmp_path: Path) -> None:
    job = _job(tmp_path, u01=UPPER)
    with pytest.raises(TargetError, match=r"no readable validation/final\.json") as caught:
        _normalize(job, stage="final")
    assert caught.value.code() == "OW_TARGET_NORMALIZE_STALE"


def test_a_clean_report_over_clean_bytes_changes_nothing(tmp_path: Path) -> None:
    """Ruling 2: the report names the rows. A report with no normalize finding names none."""
    job = _job(tmp_path, u01='<section>\n  <p class="lead">One.</p>\n</section>\n')
    _checked(job)
    assert (dict(_normalize(job, stage="early").changed)) == {}


def _two_rows() -> ConstructTable:
    """owtext's table plus `attr.id.upper`, a second normalize row its rules never report."""
    raw = tomllib.loads((HERE / "constructs.toml").read_text(encoding="utf-8"))
    raw["construct"].append(
        {
            "id": "attr.id.upper",
            "normalizes_to": "attr.id",
            "disposition": "normalize",
            "normalizer": "lower_ascii",
            "round_trip": "normalized",
            "code": "OW_TARGET_CLASS_NOT_LOWER",
            "severity": "warning",
            "canonical": "lower-case ASCII ids",
            "since": "0.1.0",
        }
    )
    return ConstructTable.parse(raw, NORMALIZERS, source="constructs.toml")


BOTH = '<section>\n  <p class="Lead" id="Intro">One.</p>\n</section>\n'


def test_without_a_report_every_normalize_row_runs(tmp_path: Path) -> None:
    table = _two_rows()
    job = _job(tmp_path, table, u01=BOTH)
    done = _normalize(job, constructs=table)
    assert dict(done.changed["u01"]) == {"attr.class.upper": 1, "attr.id.upper": 1}
    assert 'class="lead" id="intro"' in _text(job, "u01")


def test_a_report_runs_only_the_rows_its_findings_name(tmp_path: Path) -> None:
    """Ruling 2: owtext's rules report the class row and never the id row."""
    table = _two_rows()
    job = _job(tmp_path, table, u01=BOTH)
    check(job, OwTextCompiler(), target="owtext", constructs=table, stage="early")
    done = _normalize(job, constructs=table, stage="early")
    assert dict(done.changed["u01"]) == {"attr.class.upper": 1}
    assert 'class="lead" id="Intro"' in _text(job, "u01")


def test_construct_runs_the_one_row_it_names(tmp_path: Path) -> None:
    table = _two_rows()
    job = _job(tmp_path, table, u01=BOTH)
    done = _normalize(job, constructs=table, construct="attr.id.upper")
    assert dict(done.changed["u01"]) == {"attr.id.upper": 1}
    assert 'class="Lead" id="intro"' in _text(job, "u01")


@pytest.mark.parametrize("construct", ["attr.class", "elem.p", "attr.nope"])
def test_a_construct_that_is_no_normalize_row_is_unknown(construct: str, tmp_path: Path) -> None:
    job = _job(tmp_path, u01=UPPER)
    with pytest.raises(NotFoundError, match="is not a normalize row of owtext/1") as caught:
        _normalize(job, construct=construct)
    assert caught.value.code() == "OW_CONSTRUCT_UNKNOWN"
    assert "those are attr.class.upper" in str(caught.value)


def test_unit_narrows_the_run(tmp_path: Path) -> None:
    job = _job(tmp_path, u01=UPPER, u02=UPPER)
    done = _normalize(job, unit="u02", construct="attr.class.upper")
    assert done.written == ("u02.html",)
    assert _text(job, "u01") == UPPER


# ---------------------------------------------------------------------------------------------
# Rulings 4-6: what is refused, and that nothing is written
# ---------------------------------------------------------------------------------------------


def test_a_normalizer_that_does_not_settle_is_refused(tmp_path: Path) -> None:
    job = _job(tmp_path, u01=UPPER)
    with pytest.raises(TargetError, match="the normalizer is not idempotent") as caught:
        _normalize(job, normalizers={"lower_ascii": lambda value: value + "x"})
    assert caught.value.code() == "OW_TARGET_NORMALIZE_REFUSED"
    assert _text(job, "u01") == UPPER


def test_a_normalizer_that_is_not_loaded_is_refused(tmp_path: Path) -> None:
    job = _job(tmp_path, u01=UPPER)
    with pytest.raises(TargetError, match="names normalizer 'lower_ascii', which is not loaded"):
        _normalize(job, normalizers={})


def test_a_style_subproperty_row_is_refused(tmp_path: Path) -> None:
    """Ruling 4: a sub-property's splice is not built, so the row is named, not skipped."""
    raw = tomllib.loads((HERE / "constructs.toml").read_text(encoding="utf-8"))
    for row in raw["construct"]:
        if row["id"] == "attr.class":
            row["selector"] = "@style|color"
    table = ConstructTable.parse(raw, NORMALIZERS, source="constructs.toml")
    job = _job(tmp_path, table, u01='<section>\n  <p style="color: RED">One.</p>\n</section>\n')
    with pytest.raises(TargetError, match=r"a subproperty, and normalize rewrites an attribute"):
        _normalize(job, constructs=table)


def test_one_unit_that_does_not_reparse_writes_nothing_anywhere(tmp_path: Path) -> None:
    bad = '<section>\n  <p class="Lead">unclosed\n</section>\n'
    job = _job(tmp_path, u01=UPPER, u02=bad)
    with pytest.raises(TargetError, match=r"il/u02.html does not reparse") as caught:
        _normalize(job)
    assert caught.value.code() == "OW_TARGET_NORMALIZE_REFUSED"
    assert (_text(job, "u01"), _text(job, "u02")) == (UPPER, bad)
    assert sorted(p.name for p in (job / "il").iterdir()) == ["il.toml", "u01.html", "u02.html"]


def test_undecodable_bytes_are_refused(tmp_path: Path) -> None:
    job = _job(tmp_path, u01=UPPER)
    (job / "il" / "u01.html").write_bytes(b'<section><p class="A">\xff</p></section>')
    with pytest.raises(TargetError, match="does not read") as caught:
        _normalize(job)
    assert caught.value.code() == "OW_TARGET_NORMALIZE_REFUSED"


def test_no_file_but_the_ils_is_left_behind(tmp_path: Path) -> None:
    job = _job(tmp_path, u01=UPPER, u02=UPPER)
    _normalize(job)
    assert sorted(p.name for p in (job / "il").iterdir()) == ["il.toml", "u01.html", "u02.html"]
