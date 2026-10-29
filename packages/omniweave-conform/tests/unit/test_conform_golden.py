"""`omniweave_conform.golden`: a store's Reductions, read back, and judged per document. D848.

`reductions()` runs over hand-written sources, so this file opens no store. `changes()` runs over
the goldens this repository commits, varied one way at a time, so each class it returns is
reached with real Reductions rather than a toy.
"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest
from omniweave_conform import golden
from omniweave_conform.churn import Reductions, load_decomposition
from omniweave_conform.golden import CORPUS, changes, document_paths, read_tree, reductions
from omniweave_core.archive import BlockExport, DocHeader
from omniweave_core.model import (
    Addr,
    Block,
    BlockId,
    Cite,
    Kind,
    Layer,
    Method,
    OriginNone,
    Quote,
    Trust,
)

REPO = Path(__file__).resolve().parents[4]
DECOMPOSITION = load_decomposition(REPO / "fixtures" / "goldens" / "DECOMPOSITION.toml")
PDF = f"{CORPUS}/parse.pdf.pdfium@1/gen01p.pdf"


def _block(driver: str, schema_v: int) -> BlockExport:
    block = Block(
        id=BlockId(1),
        addr=Addr("p0/0"),
        cite=Cite("d1#1"),
        doc_ord=1,
        gen=1,
        page=0,
        parent=None,
        ord=0,
        kind=Kind.PARAGRAPH,
        raw_kind=None,
        layer=Layer.BODY,
        label=None,
        text="body",
        content_digest=bytes(16),
        layout_digest=None,
        revision=0,
        quad=None,
        origin=OriginNone(),
        span=None,
        producer_id=1,
        method=Method.NATIVE,
        trust=Trust.EXTRACTED,
        quote=Quote.NORMALIZED,
    )
    return BlockExport(
        block=replace(block, origin_driver=driver, driver_schema_v=schema_v), producer=0
    )


class _Source:
    def __init__(self, uri: str, blocks: tuple[BlockExport, ...]) -> None:
        self._uri, self._blocks = uri, blocks

    def header(self) -> DocHeader:
        source = {"page_count": 1, "uri": self._uri}
        return DocHeader(
            doc_key="ab" * 16, gen=1, status="ok", source=source, declared={}, achieved={}
        )

    def blocks(self) -> tuple[BlockExport, ...]:
        return self._blocks

    def rels(self) -> tuple[()]:
        return ()

    def grids(self) -> tuple[()]:
        return ()

    def diags(self) -> tuple[()]:
        return ()


class _Connection:
    def __init__(self, ords: list[int]) -> None:
        self._ords = ords

    def execute(self, sql: str) -> list[tuple[int]]:
        assert sql == "SELECT doc_ord FROM doc ORDER BY doc_ord"
        return [(n,) for n in self._ords]


SOURCES: dict[int, _Source] = {
    1: _Source("file:///C:/docs/omniweave-office/deck.pptx", (_block("parse.office.anydoc", 1),)),
    2: _Source("c:\\docs\\omniweave-pdf\\gen01p.pdf", (_block("parse.pdf.pdfium", 3),)),
    3: _Source("file:///C:/docs/refused.pdf", ()),
}


# --- rulings 1 and 3: reductions() --------------------------------------------------------------


def test_reductions_names_each_document_by_driver_and_file(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(golden, "StoreExportSource", lambda _c, _cas, ord_: SOURCES[ord_])
    tree = reductions(_Connection([1, 2, 3]), Path("cas"), corpus="core@test")
    assert sorted(tree) == [
        f"core@test/parse.office.anydoc@1/deck.pptx.{kind}"
        for kind in ("outline", "pages", "shape")
    ] + [
        f"core@test/parse.pdf.pdfium@3/gen01p.pdf.{kind}" for kind in ("outline", "pages", "shape")
    ]
    shape = tree["core@test/parse.pdf.pdfium@3/gen01p.pdf.shape"]
    assert shape.startswith(
        "owshape/1  corpus=core@test  doc=" + "ab" * 16 + "  driver=parse.pdf.pdfium@3"
    )
    assert all(text.endswith("\n") and "\r" not in text for text in tree.values())


def test_a_document_with_no_blocks_has_no_reductions(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(golden, "StoreExportSource", lambda _c, _cas, ord_: SOURCES[ord_])
    assert reductions(_Connection([3]), Path("cas")) == {}


# --- read_tree() and document_paths() --------------------------------------------------------


def test_read_tree_reads_one_corpus_and_only_reductions(tmp_path: Path) -> None:
    base = tmp_path / "fixtures" / "goldens"
    for rel, text in {
        f"{CORPUS}/drv@1/a.pdf.shape": "s\n",
        f"{CORPUS}/drv@1/a.pdf.pages": "p\n",
        f"{CORPUS}/drv@1/notes.txt": "not a reduction\n",
        "core@2026.09/drv@1/b.pdf.shape": "another corpus\n",
        "DECOMPOSITION.toml": "x\n",
    }.items():
        (base / rel).parent.mkdir(parents=True, exist_ok=True)
        (base / rel).write_bytes(text.encode())
    assert read_tree(tmp_path) == {
        f"{CORPUS}/drv@1/a.pdf.pages": "p\n",
        f"{CORPUS}/drv@1/a.pdf.shape": "s\n",
    }
    assert read_tree(tmp_path, "core@1999.01") == {}


def test_document_paths_groups_the_three_kinds_by_document() -> None:
    tree = {"c/d@1/x.pdf.shape": "s", "c/d@1/x.pdf.pages": "p", "c/d@1/y.md.outline": "o"}
    assert document_paths(tree) == {
        "c/d@1/x.pdf": Reductions("s", "p", ""),
        "c/d@1/y.md": Reductions("", "", "o"),
    }


# --- ruling 4: changes(), over the committed goldens --------------------------------------------

COMMITTED = read_tree(REPO)


def _vary(path: str, old: str, new: str) -> dict[str, str]:
    assert COMMITTED[path].count(old) >= 1, (path, old)
    return {**COMMITTED, path: COMMITTED[path].replace(old, new, 1)}


def test_the_repository_commits_its_goldens() -> None:
    """D848: every document, three Reductions each -- a `.shape`, a `.pages` and an `.outline`.

    The count is DERIVED from the tree rather than typed: D1004's twenty labelled office documents
    took it from 26 documents to 46, and what this test is for is the invariant that each one has
    exactly its three Reductions under one of the three drivers, which a literal hides.
    """
    documents = {path.rsplit(".", 1)[0] for path in COMMITTED}
    assert len(documents) == 49
    assert len(COMMITTED) == 3 * len(documents)
    for document in documents:
        assert {path for path in COMMITTED if path.rsplit(".", 1)[0] == document} == {
            f"{document}.{suffix}" for suffix in ("shape", "pages", "outline")
        }
    assert {path.split("/")[1] for path in COMMITTED} == {
        "parse.office.anydoc@1",
        "parse.pdf.pdfium@1",
        "parse.text.builtin@1",
    }


def test_identical_trees_have_no_changes() -> None:
    assert changes(COMMITTED, dict(COMMITTED), DECOMPOSITION) == []


def test_a_new_and_a_lost_document_are_structural() -> None:
    fresh = {k: v for k, v in COMMITTED.items() if not k.startswith(PDF)}
    fresh[f"{CORPUS}/parse.pdf.pdfium@1/new.pdf.shape"] = COMMITTED[f"{PDF}.shape"]
    found = {
        c.doc: (c.churn.cls, c.churn.reasons) for c in changes(COMMITTED, fresh, DECOMPOSITION)
    }
    assert found == {
        PDF: ("structural", ("the document is gone",)),
        f"{CORPUS}/parse.pdf.pdfium@1/new.pdf": ("structural", ("a new document",)),
    }


def test_a_digest_only_page_change_is_incidental() -> None:
    pages = COMMITTED[f"{PDF}.pages"]
    digest = pages.split("cdig=", 1)[1].split()[0]
    [change] = changes(
        COMMITTED, _vary(f"{PDF}.pages", f"cdig={digest}", "cdig=00000000"), DECOMPOSITION
    )
    assert (change.doc, change.churn.cls) == (PDF, "incidental")


def test_a_page_count_moved_with_no_shape_delta_is_unexplained() -> None:
    [change] = changes(COMMITTED, _vary(f"{PDF}.pages", " n=", " n=9"), DECOMPOSITION)
    assert change.churn.cls == "unexplained"


def test_a_shape_counter_that_moved_is_structural() -> None:
    [change] = changes(
        COMMITTED,
        _vary(f"{PDF}.shape", "achieved.marks false", "achieved.marks true"),
        DECOMPOSITION,
    )
    assert change.churn.cls == "structural"
    assert [d.key for d in change.churn.delta] == ["achieved.marks"]
