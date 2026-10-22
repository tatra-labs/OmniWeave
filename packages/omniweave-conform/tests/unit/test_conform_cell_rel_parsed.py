"""`cell_rel` over a PARSED document: a real DOCX through the office driver, judged on it. D932.

13:1261's transposed-table defect, *"every `table` and `cell_rel` assertion fails while every
`present` assertion still passes"*, had only ever run its `cell_rel` half over a hand-built Doc
(D877). Here the table is written into a DOCX, parsed by `parse.office.anydoc`, decoded into a
candidate store by `labels.candidate()` and read back by `labels.opened()`, which is what the
parse eval suite now hands `judge()`. The same assertions run over the table and over its
transpose: every one passes on the first and fails on the second, on the owdoc evaluator.

The assertions name page 1, as a label does. Until D932 `cells` compared that with `Block.page`,
which is 0-based, so on this one-page document every assertion would have looked for page 2
and failed on the untransposed table too; the first half of this test is what catches that.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from typing import Any

from omniweave_conform import labels
from omniweave_conform.harness import run_parse
from omniweave_conform.judge import judge
from omniweave_conform.subject import Subject
from omniweave_core.store.oweval import Assertion

REPO = Path(__file__).resolve().parents[4]
OFFICE_CARD = REPO / "packages/omniweave-office/src/omniweave_office/driver.toml"
DOC = "table.docx"

_SPEC = importlib.util.spec_from_file_location(
    "omniweave_gen_office_fixtures", REPO / "fixtures/gen/gen_office_fixtures.py"
)
assert _SPEC is not None and _SPEC.loader is not None
office = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = office
_SPEC.loader.exec_module(office)

ROWS = [["Item", "Q1", "Q2", "Q3"], *[[f"r{r}", *[f"{r}.{q}" for q in (1, 2, 3)]] for r in (1, 2)]]
"""A header row and a header column: six cells, each with a row heading and a column heading."""


def _docx(rows: list[list[str]]) -> bytes:
    """A one-table DOCX, its first row a header row, built as the office generator builds one."""
    cell = "<w:tc><w:p><w:r><w:t>{}</w:t></w:r></w:p></w:tc>"
    head = '<w:tr><w:trPr><w:tblHeader w:val="true"/></w:trPr>'
    body = "".join(
        (head if index == 0 else "<w:tr>") + "".join(cell.format(v) for v in row) + "</w:tr>"
        for index, row in enumerate(rows)
    )
    grid = "<w:gridCol/>" * len(rows[0])
    document = (
        office.XML + f'<w:document xmlns:w="{office.W}"><w:body>'
        "<w:p><w:r><w:t>Figures</w:t></w:r></w:p>"
        f"<w:tbl><w:tblPr/><w:tblGrid>{grid}</w:tblGrid>{body}</w:tbl>"
        "</w:body></w:document>"
    )
    return office.zip_bytes(
        [
            (
                "[Content_Types].xml",
                office.content_types(
                    '<Override PartName="/word/document.xml" ContentType="application/vnd'
                    '.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>'
                ),
            ),
            ("_rels/.rels", office.rels(office.rel("rId1", "officeDocument", "word/document.xml"))),
            ("word/document.xml", document.encode()),
        ]
    )


def _assertion(spec: dict[str, Any], aid: str) -> Assertion:
    return Assertion(
        assertion_id=aid,
        corpus_id="d932",
        corpus_version="1",
        doc=DOC,
        page=1,
        type="cell_rel",
        spec=spec,
        addr=None,
        evaluable_in="owdoc",
        checked="verified",
        derived_from_sha256="sha256:" + "ab" * 32,
        max_diffs=0,
        slices=("docx",),
    )


CELLS = [
    _assertion(
        {"cell": f"{r}.{q}", "top_heading": f"Q{q}", "left": f"r{r}" if q == 1 else f"{r}.{q - 1}"},
        f"c{r}{q}",
    )
    for r in (1, 2)
    for q in (1, 2, 3)
]
"""Each cell's column heading and its left neighbour. Not `left_heading`: a DOCX table declares
header ROWS (`w:tblHeader`) and never a header column, so its grid has no left heading, which is
`cells` ruling 3's reading and the right one."""


def _judged(tmp_path: Path, rows: list[list[str]]) -> Any:
    fixtures = tmp_path / "fixtures"
    fixtures.mkdir(parents=True)
    (fixtures / DOC).write_bytes(_docx(rows))
    found = Subject.of(OFFICE_CARD, fixtures_dir=fixtures, workdir=tmp_path / "subject")
    fixture = next(f for f in found.fixtures if f.path.name == DOC)
    parse = run_parse(found.instantiate(), fixture, tmp_path / "run")
    pages = labels.candidate(parse, found.card, doc=DOC, workdir=tmp_path / "candidate")
    with labels.opened({DOC: tmp_path / "candidate" / labels.STORE}) as docs:
        return judge(CELLS, pages, run_id="r", docs=docs)


def test_every_cell_rel_passes_over_the_parsed_table(tmp_path: Path) -> None:
    judged = _judged(tmp_path, ROWS)
    assert judged.not_run == ()
    assert judged.failed == (), [v.explanation for v in judged.verdicts if not v.passed]
    assert (judged.passed, {v.evaluator for v in judged.verdicts}) == (6, {"owdoc"})


def test_a_transposed_table_fails_every_cell_rel_over_the_parsed_document(tmp_path: Path) -> None:
    transposed = [list(column) for column in zip(*ROWS, strict=True)]
    judged = _judged(tmp_path, transposed)
    assert (judged.passed, len(judged.failed), judged.not_run) == (0, 6, ())
    assert all("relations missed" in v.explanation for v in judged.verdicts), [
        v.explanation for v in judged.verdicts
    ]
