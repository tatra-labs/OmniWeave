"""The register's slice globs bind to the corpus's own declarations. **D983.**

13-quality.md:1148-1152: *"`eval_metric.slice_key` is **not** the router's Slice ... the harness's
is the corpus's own declaration -- `[fixture.tests] slices` in a Tier-A sidecar, `slices` in an
`eval_assertion` row -- and a `[[gate]]` row's `slice` field is a path glob matched against it"*,
and `release.py` matches it with `fnmatchcase`.

Nothing asserted the two halves meet. They did not: until D983 no shipped sidecar declared a slice,
so every verdict landed on `*` (`judge` ruling 5) while the register's rows name `office/*`,
`pdf/born_digital/*` and `*/has_merges=1`. A floor whose glob matches nothing is law over an empty
set -- green, and measuring no document at all. These tests are that gap closed from both sides.
"""

from __future__ import annotations

import tomllib
from fnmatch import fnmatchcase
from pathlib import Path
from typing import Any, Final

import pytest
from omniweave_conform import labels, structure

REPO: Final = Path(__file__).resolve().parents[4]
REGISTER: Final = REPO / "eval" / "gates.toml"
FIXTURE_DIRS: Final = (
    REPO / "packages" / "omniweave-office" / "fixtures",
    REPO / "packages" / "omniweave-pdf" / "fixtures",
)
SIDECAR: Final = ".meta.toml"
HAS_MERGES: Final = "has_merges=1"


def _register() -> list[dict[str, Any]]:
    return tomllib.loads(REGISTER.read_text(encoding="utf-8"))["gate"]


def _parse_floors() -> list[dict[str, Any]]:
    """The accuracy floors D983 landed: the `parse` suite's rows over a labelled corpus."""
    return [row for row in _register() if row["suite"] == "parse" and row["kind"] == "floor"]


def _labelled() -> list[Path]:
    """Every committed fixture that carries labels or a structure reference."""
    return sorted(
        path
        for directory in FIXTURE_DIRS
        for path in directory.iterdir()
        if path.is_file()
        and not path.name.endswith((SIDECAR, labels.SUFFIX, structure.SUFFIX))
        and (labels.labels_of(path).is_file() or structure.reference_of(path).is_file())
    )


def _slices(fixture: Path) -> tuple[str, ...]:
    """`[fixture.tests] slices`, in declared order."""
    sidecar = fixture.with_name(fixture.name + SIDECAR)
    if not sidecar.is_file():
        return ()
    tests = tomllib.loads(sidecar.read_text(encoding="utf-8")).get("fixture", {}).get("tests", {})
    declared = tests.get("slices", []) if isinstance(tests, dict) else []
    return tuple(str(one) for one in declared)


def test_every_labelled_fixture_declares_a_slice() -> None:
    """The ratchet: a label on a fixture with no slice scores into `*` and no floor reads it."""
    assert [path.name for path in _labelled() if not _slices(path)] == []


def test_the_three_floors_are_registered_with_the_plans_numbers() -> None:
    rows = {(row["metric"], row["slice"]): row for row in _parse_floors()}
    assert set(rows) == {
        ("structure_f1", "office/*"),
        ("order_acc", "pdf/born_digital/*"),
        ("table_rel_acc", "*/has_merges=1"),
    }
    assert rows["structure_f1", "office/*"]["budget"] == pytest.approx(0.90)
    assert rows["order_acc", "pdf/born_digital/*"]["budget"] == pytest.approx(0.75)
    assert rows["table_rel_acc", "*/has_merges=1"]["budget"] == pytest.approx(0.70)
    for row in rows.values():
        assert row["class"] == "blocking"
        assert row["guard"] > 0, "13:1097-1100 gives every accuracy floor a guard band"
        assert row["owner"] and row["review_by"], "Q-G17 reads both"
        assert row["computed"].strip(), "13:1087: a floor with no definition is not a gate"


@pytest.mark.parametrize("row", _parse_floors(), ids=lambda row: f"{row['metric']}@{row['slice']}")
def test_every_floor_glob_matches_a_slice_the_corpus_declares(row: dict[str, Any]) -> None:
    """The half that was broken: `fnmatchcase` over the sidecars' own spellings."""
    declared = {one for path in _labelled() for one in _slices(path)}
    matched = sorted(one for one in declared if fnmatchcase(one, row["slice"]))
    assert matched, (
        f"{row['metric']}@{row['slice']} matches none of {sorted(declared)}, so the floor is law "
        "over an empty set"
    )


def test_every_declared_slice_is_read_by_some_floor() -> None:
    """And the other direction: a slice no row reads is a declaration nothing scores."""
    globs = [row["slice"] for row in _parse_floors()]
    declared = {one for path in _labelled() for one in _slices(path)}
    assert [one for one in sorted(declared) if not any(fnmatchcase(one, g) for g in globs)] == []


def test_a_merge_bearing_document_declares_has_merges_first() -> None:
    """`judge` ruling 5: a verdict's slice is the assertion's FIRST slice, so the order decides
    which rows `*/has_merges=1` ever sees."""
    merged = {
        path.name: _slices(path)
        for path in _labelled()
        if any(HAS_MERGES in s for s in _slices(path))
    }
    assert merged, "a floor over an empty set is law over nothing"
    for name, declared in merged.items():
        assert declared[0].endswith(HAS_MERGES), f"{name} declares {declared}"
        assert sum(1 for one in declared if HAS_MERGES in one) == 1, f"{name} declares {declared}"


def test_the_has_merges_glob_reads_only_the_merge_bearing_documents() -> None:
    """A spreadsheet with no merged cell is not in the merge slice, or the floor is measured over
    documents the metric is not about."""
    row = next(one for one in _parse_floors() if one["metric"] == "table_rel_acc")
    inside = {
        path.name
        for path in _labelled()
        if any(fnmatchcase(one, row["slice"]) for one in _slices(path))
    }
    declares = {
        path.name for path in _labelled() if any(HAS_MERGES in one for one in _slices(path))
    }
    assert inside == declares, "the glob reads exactly the documents that declare the facet"
    assert "rows.csv" not in inside and "sheet.xls" not in inside
    assert len(inside) >= 6, (
        "D1005 added three merged-cell documents to the three D983 declared, because three"
        " five-cell tables cannot carry min_slice_n = 30 honest relations"
    )
