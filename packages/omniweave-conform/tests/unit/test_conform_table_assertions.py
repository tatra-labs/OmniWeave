"""Every committed `table` and `cell_rel` assertion, judged against its PARSED fixture. **D1005.**

`table_rel_acc`'s register row is `*/has_merges=1` (13-quality.md:1099) and `min_slice_n = 30`, so
the floor computed nothing while three documents carried five-cell tables between them. D1005 adds
three merged-cell documents with room for honest relations; what this file guarantees is that the
relations are TRUE of the documents, rather than true of the outline I wrote them from.

Each fixture goes through `parse.office.anydoc` for real, is decoded by `labels.candidate()` and
read back by `labels.opened()` -- which is what the parse eval suite hands `judge()` (D932) -- and
every committed `table` and `cell_rel` assertion is judged on it. A drafted label that is wrong
about its own document is the one defect a reviewer cannot be asked to catch for us: they are
asked whether a claim is one the corpus should make, not whether the parser happens to satisfy it.

This is not a claim that the assertions are VERIFIED. None is: `checked` stays absent until the
reviewer writes it (D913), and an unchecked assertion runs and never scores (13:1022). What runs
here is the "runs" half.
"""

from __future__ import annotations

import tomllib
from pathlib import Path

import pytest
from omniweave_conform import labels
from omniweave_conform.harness import run_parse
from omniweave_conform.judge import judge
from omniweave_conform.subject import Subject

REPO = Path(__file__).resolve().parents[4]
OFFICE_CARD = REPO / "packages/omniweave-office/src/omniweave_office/driver.toml"
FIXTURES = REPO / "packages/omniweave-office/fixtures"
RELATIONAL = frozenset({"table", "cell_rel"})


def _relational() -> list[str]:
    """Every committed office fixture whose assertions file carries a `table` or `cell_rel` row."""
    out = []
    for path in sorted(FIXTURES.glob(f"*{labels.SUFFIX}")):
        rows = tomllib.loads(path.read_text(encoding="utf-8")).get("assertion", [])
        if any(row.get("type") in RELATIONAL for row in rows):
            out.append(path.name.removesuffix(labels.SUFFIX))
    return out


NAMES = _relational()


@pytest.mark.parametrize("name", NAMES)
def test_every_relational_assertion_holds_over_the_parsed_fixture(
    name: str, tmp_path: Path
) -> None:
    """The relations are the document's, read back through the driver rather than asserted."""
    found = Subject.of(OFFICE_CARD, fixtures_dir=FIXTURES, workdir=tmp_path / "subject")
    fixture = next(one for one in found.fixtures if one.path.name == name)
    every = labels.load(fixture.path, fixtures_dir=FIXTURES, corpus_id="d1005", corpus_version="1")
    wanted = tuple(one for one in every if one.type in RELATIONAL)
    assert wanted, f"{name} was selected for carrying one"
    parse = run_parse(found.instantiate(), fixture, tmp_path / "run")
    pages = labels.candidate(parse, found.card, doc=name, workdir=tmp_path / "candidate")
    with labels.opened({name: tmp_path / "candidate" / labels.STORE}) as docs:
        judged = judge(wanted, pages, run_id="d1005", docs=docs)
    assert judged.failed == (), [one.explanation for one in judged.verdicts if not one.passed]
    assert judged.not_run == (), [one.assertion_id for one in judged.not_run]
    assert judged.passed == len(wanted)


def test_the_merged_cell_slice_can_reach_min_slice_n() -> None:
    """`table_rel_acc` counts the TEXT evaluator's verdicts (`rollup` ruling 1, and `eval_run`
    passes `evaluator="text"`), so its population is the `table` rows alone: a `cell_rel` runs on
    `owdoc` and its verdict is recorded outside that rate. The floor needs thirty of them in one
    slice, and `*/has_merges=1` is the row's glob."""
    from omniweave_core.drivers.card import MIN_SLICE_N  # noqa: PLC0415

    by_type: dict[str, int] = {}
    for path in sorted(FIXTURES.glob(f"*{labels.SUFFIX}")):
        for row in tomllib.loads(path.read_text(encoding="utf-8")).get("assertion", []):
            if row.get("type") in RELATIONAL and (row.get("slices") or [None])[0] == (
                "office/has_merges=1"
            ):
                by_type[row["type"]] = by_type.get(row["type"], 0) + 1
    assert by_type["table"] >= MIN_SLICE_N, by_type
    assert by_type["cell_rel"] > 0, "V10-16 wants a committed cell_rel label to exist at all"
