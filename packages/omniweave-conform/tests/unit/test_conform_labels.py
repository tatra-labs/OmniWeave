"""`omniweave_conform.labels` and the parse suite's labelled half. D912.

A fixture's labels are `<file>.assertions.toml` beside it. These tests write labels for copies of
two committed fixtures in `tmp_path`, never beside the originals: `rich.docx`, whose table the
`table` assertion reads as Markdown, and `gen01p.pdf`, whose verbatim claims the scratch store
checks against the fixture's own bytes.
"""

from __future__ import annotations

import dataclasses
import shutil
from itertools import count
from pathlib import Path
from typing import Any

import pytest
from omniweave_conform import eval_run, labels
from omniweave_conform.harness import load_fixtures, run_parse
from omniweave_conform.subject import Subject
from omniweave_core.errors import QualityError

REPO = Path(__file__).resolve().parents[4]
OFFICE_CARD = REPO / "packages/omniweave-office/src/omniweave_office/driver.toml"
PDF_CARD = REPO / "packages/omniweave-pdf/src/omniweave_pdf/driver.toml"
RICH = REPO / "packages/omniweave-office/fixtures/rich.docx"
GEN01P = REPO / "packages/omniweave-pdf/fixtures/gen01p.pdf"
HEAD = 'schema = "omniweave.assertions/1"\n'


def _corpus(tmp_path: Path, labels_text: str | None, *, source: Path = RICH) -> Path:
    fixtures = tmp_path / "corpus"
    fixtures.mkdir(parents=True, exist_ok=True)
    shutil.copy(source, fixtures / source.name)
    if labels_text is not None:
        (fixtures / (source.name + labels.SUFFIX)).write_text(
            HEAD + labels_text, encoding="utf-8", newline="\n"
        )
    return fixtures


def _load(fixtures: Path, name: str = "rich.docx") -> tuple[Any, ...]:
    return labels.load(
        fixtures / name, fixtures_dir=fixtures, corpus_id="corpus", corpus_version="v1"
    )


# ---------------------------------------------------------------------------------------------
# Rulings 1-5: the file
# ---------------------------------------------------------------------------------------------


def test_a_row_is_its_keys_and_the_rest_is_its_spec(tmp_path: Path) -> None:
    fixtures = _corpus(
        tmp_path,
        '[[assertion]]\nid = "order-1"\ntype = "order"\npage = 1\nbefore = "Quarterly"\n'
        'after = "Figures"\nchecked = "verified"\nmax_diffs = 1\nslices = ["office/docx"]\n',
    )
    (one,) = _load(fixtures)
    assert one.assertion_id == "corpus/rich.docx#order-1@v1"
    assert (one.corpus_id, one.corpus_version, one.doc, one.page) == (
        "corpus",
        "v1",
        "rich.docx",
        1,
    )
    assert (one.type, dict(one.spec)) == ("order", {"before": "Quarterly", "after": "Figures"})
    assert (one.checked, one.max_diffs, one.slices) == ("verified", 1, ("office/docx",))
    assert (one.evaluable_in, one.addr) == ("text", None)
    assert len(one.derived_from_sha256) == 64


def test_an_absent_checked_is_null_and_owdoc_types_default_to_owdoc(tmp_path: Path) -> None:
    fixtures = _corpus(
        tmp_path,
        '[[assertion]]\nid = "a"\ntype = "present"\ntext = "first item"\n'
        '[[assertion]]\nid = "b"\ntype = "footnote"\ntext = "a note"\n',
    )
    present, footnote = _load(fixtures)
    assert (present.checked, present.page, present.evaluable_in) == (None, None, "text")
    assert footnote.evaluable_in == "owdoc"


def test_slices_default_to_the_sidecar_s(tmp_path: Path) -> None:
    fixtures = _corpus(tmp_path, '[[assertion]]\nid = "a"\ntype = "present"\ntext = "x"\n')
    (fixtures / "rich.docx.meta.toml").write_text(
        '[fixture]\nsha256 = "x"\n[fixture.tests]\nslices = ["office/docx", "office"]\n',
        encoding="utf-8",
    )
    (one,) = _load(fixtures)
    assert one.slices == ("office/docx", "office")


def test_a_fixture_with_no_labels_has_none(tmp_path: Path) -> None:
    assert _load(_corpus(tmp_path, None)) == ()


@pytest.mark.parametrize(
    ("text", "said"),
    [
        ('[[assertion]]\nid = "a"\ntype = "guess"\n', "type 'guess' is not one of 13:998-1013's"),
        ('[[assertion]]\nid = "A b"\ntype = "present"\n', "id 'A b' is not"),
        ('[[assertion]]\nid = "a"\ntype = "present"\npage = 0\n', "page 0 is a 1-based"),
        ('[[assertion]]\nid = "a"\ntype = "present"\nchecked = "yes"\n', "checked 'yes' is"),
        ('[[assertion]]\nid = "a"\ntype = "present"\nmax_diffs = -1\n', "max_diffs -1"),
        ('[[assertion]]\nid = "a"\ntype = "present"\nslices = "x"\n', "slices is a list"),
        ('[[assertion]]\nid = "a"\ntype = "present"\nevaluable_in = "pdf"\n', "evaluable_in 'pdf'"),
        (
            '[[assertion]]\nid = "a"\ntype = "present"\n[[assertion]]\nid = "a"\ntype = "absent"\n',
            "id 'a' repeats",
        ),
        ("extra = 1\n", "unknown key(s) ['extra']"),
    ],
)
def test_a_malformed_row_is_refused_naming_the_file_and_row(
    tmp_path: Path, text: str, said: str
) -> None:
    fixtures = _corpus(tmp_path, text)
    with pytest.raises(QualityError, match=r"rich\.docx\.assertions\.toml") as caught:
        _load(fixtures)
    assert said in str(caught.value)


def test_another_schema_is_refused(tmp_path: Path) -> None:
    fixtures = _corpus(tmp_path, None)
    (fixtures / "rich.docx.assertions.toml").write_text('schema = "x/2"\n', encoding="utf-8")
    with pytest.raises(QualityError, match="schema is 'x/2'"):
        _load(fixtures)


def test_labels_are_no_input_to_a_driver(tmp_path: Path) -> None:
    fixtures = _corpus(tmp_path, '[[assertion]]\nid = "a"\ntype = "present"\ntext = "x"\n')
    assert [f.path.name for f in load_fixtures(fixtures)] == ["rich.docx"]


# ---------------------------------------------------------------------------------------------
# Ruling 6: the candidate
# ---------------------------------------------------------------------------------------------


def _candidate(tmp_path: Path, card: Path, source: Path) -> dict[tuple[str, int], str]:
    found = Subject.of(card, fixtures_dir=source.parent, workdir=tmp_path / "subject")
    fixture = next(f for f in found.fixtures if f.path.name == source.name)
    parse = run_parse(found.instantiate(), fixture, tmp_path / "run")
    return labels.candidate(parse, found.card, doc=source.name, workdir=tmp_path / "candidate")


def test_a_page_is_the_markdown_ow_serves_its_tables_included(tmp_path: Path) -> None:
    pages = _candidate(tmp_path, OFFICE_CARD, RICH)
    assert list(pages) == [("rich.docx", 1)]
    page = pages["rich.docx", 1]
    assert page.startswith("# Quarterly report")
    assert "| Q1 | 120 |" in page


def test_a_verbatim_claim_is_checked_against_the_fixture_and_commits(tmp_path: Path) -> None:
    """Ruling 6: without the source part a PDF's verbatim blocks would quarantine the parse."""
    pages = _candidate(tmp_path, PDF_CARD, GEN01P)
    assert pages["gen01p.pdf", 1].startswith("Article 1. Schedule and severance")


# ---------------------------------------------------------------------------------------------
# eval_run rulings 22-24: the parse suite's labelled half
# ---------------------------------------------------------------------------------------------


def _register(fixtures: Path, card: Path = OFFICE_CARD) -> dict[str, Any]:
    return {
        "subject": [{"card": str(card), "fixtures": fixtures.name, "slice": "office"}],
        "gate": [],
    }


def _run(tmp_path: Path, fixtures: Path, card: Path = OFFICE_CARD) -> Any:
    ticks = count(1_000, 7)
    batch, _ = eval_run.parse(
        _register(fixtures, card),
        root=tmp_path,
        subject=None,
        witness="self",
        cassette="off",
        now_ns=lambda: next(ticks),
    )
    return batch


ORDERS = "".join(
    f'[[assertion]]\nid = "order-{n:02d}"\ntype = "order"\npage = 1\nbefore = "Quarterly report"\n'
    f'after = "first item"\nchecked = "verified"\nslices = ["office/docx"]\n'
    for n in range(30)
)
TABLE = (
    '[[assertion]]\nid = "table-q1"\ntype = "table"\npage = 1\ncell = "Q1"\nright = "120"\n'
    'up = "Quarter"\nchecked = "verified"\nslices = ["office/docx"]\n'
    '[[assertion]]\nid = "table-draft"\ntype = "table"\npage = 1\ncell = "Revenue"\n'
    'down = "120"\nslices = ["office/docx"]\n'
    '[[assertion]]\nid = "note"\ntype = "footnote"\ntext = "a note"\n'
)


def test_labels_are_judged_and_rolled_up_into_their_rates(tmp_path: Path) -> None:
    batch = _run(tmp_path, _corpus(tmp_path, ORDERS + TABLE))
    (run,) = batch.runs
    (corpus,) = batch.corpora
    assert (corpus.n_docs, corpus.n_assertions, corpus.n_checked) == (1, 33, 31)
    assert len(batch.assertions) == 33
    assert {v.assertion_id.split("#")[1].split("@")[0] for v in batch.verdicts} == {
        *(f"order-{n:02d}" for n in range(30)),
        "table-q1",
        "table-draft",
    }
    assert all(v.passed for v in batch.verdicts)
    rows = {(m.metric, m.slice_key): m for m in batch.metrics}
    order = rows["order_acc", "office/docx"]
    assert (order.value, order.n, order.state, order.truth_kind) == (1.0, 30, "ok", "rendered")
    assert rows["order_acc", "__macro__"].value == 1.0
    table = rows["table_rel_acc", "office/docx"]
    assert (table.n, table.state, table.value) == (1, "unknown", None), "1 < min_slice_n = 30"
    assert "table_rel_acc: 1 unverified assertion(s) ran and were not scored (13:1022)" in (
        run.not_measured
    )
    assert any(note.startswith("assertion corpus/rich.docx#note@") for note in run.not_measured)
    assert eval_run.PARSE_UNMEASURED[0] in run.not_measured


def test_a_failed_label_lowers_its_rate(tmp_path: Path) -> None:
    wrong = ORDERS.replace(
        'before = "Quarterly report"\nafter = "first item"',
        'before = "first item"\nafter = "Quarterly report"',
        1,
    )
    batch = _run(tmp_path, _corpus(tmp_path, wrong))
    rows = {(m.metric, m.slice_key): m for m in batch.metrics}
    assert rows["order_acc", "office/docx"].value == pytest.approx(29 / 30)
    assert sum(not v.passed for v in batch.verdicts) == 1


def test_a_relabel_is_a_new_corpus_version(tmp_path: Path) -> None:
    first = _run(tmp_path / "a", _corpus(tmp_path / "a", ORDERS)).corpora[0].version
    second = _run(tmp_path / "b", _corpus(tmp_path / "b", ORDERS + TABLE)).corpora[0].version
    unlabelled = _run(tmp_path / "c", _corpus(tmp_path / "c", None)).corpora[0].version
    assert len({first, second, unlabelled}) == 3


def test_an_unlabelled_corpus_writes_no_rate_and_says_so(tmp_path: Path) -> None:
    batch = _run(tmp_path, _corpus(tmp_path, None))
    (run,) = batch.runs
    assert (batch.assertions, batch.verdicts) == ((), ())
    assert [m.metric for m in batch.metrics] == []
    assert (
        eval_run.UNLABELLED.format(metrics="field_acc, order_acc, table_rel_acc", corpus="corpus")
        in run.not_measured
    )


def test_a_quarantined_parse_is_refused_never_an_empty_document(tmp_path: Path) -> None:
    """Ruling 6: with its source part out of reach the verbatim check cannot run, the generation
    quarantines, and no page is judged as dropped."""
    found = Subject.of(PDF_CARD, fixtures_dir=GEN01P.parent, workdir=tmp_path / "subject")
    fixture = next(f for f in found.fixtures if f.path.name == GEN01P.name)
    parse = run_parse(found.instantiate(), fixture, tmp_path / "run")
    forged = dataclasses.replace(parse, fixture=dataclasses.replace(fixture, digest="0" * 64))
    with pytest.raises(QualityError, match=r"the store quarantined parse\.pdf\.pdfium's parse"):
        labels.candidate(forged, found.card, doc=GEN01P.name, workdir=tmp_path / "candidate")
