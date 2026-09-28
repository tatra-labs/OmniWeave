"""`ow doc diff`: `rebind()`'s matcher over two generations of one document, applied to nothing.

The store is `conftest.py`'s `seeded_store` -- document `d1` at generation 1, a heading and two
paragraphs, every digest `SEED_DIGEST` -- with a second generation staged beside it the way a
quarantined re-parse leaves one (03:1298-1302): `doc.gen` stays 1, the rows sit at generation 2 with
`state = 0`, and an `OW_REBIND_UNEXPLAINED` diag records the threshold that refused them.

Generation 2 holds a copy of the heading, which rule 1 carries, and one new paragraph, which it
creates, so the two paragraphs of generation 1 are retired: carried 1, created 1, retired 2.
"""

from __future__ import annotations

import io
import json
import sqlite3  # noqa: TID251 -- the fixture stages a REAL generation.
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pytest
from omniweave.surface import doc as verb

if TYPE_CHECKING:
    from collections.abc import Sequence

PROJECT = '[corpora.handbook]\npath = ".omniweave/index.owstore"\n'
THRESHOLD = 0.9


def _code(conn: sqlite3.Connection, domain: str, name: str) -> int:
    row = conn.execute(
        "SELECT ord FROM enum_val WHERE domain = ? AND name = ?", (domain, name)
    ).fetchone()
    return int(row[0])


def _stage(store: Path, *, threshold: float = THRESHOLD) -> None:
    """Generation 2 beside the head, as a quarantine leaves it: rows, a page, and the diag."""
    conn = sqlite3.connect(store)
    try:
        producer = int(conn.execute("SELECT producer_id FROM producer").fetchone()[0])
        native = _code(conn, "method", "native")
        conn.execute(
            "INSERT INTO page(doc_ord, gen, page, page_kind, method, producer_id) "
            "VALUES(1, 2, 1, ?, ?, ?)",
            (_code(conn, "page_kind", "page"), native, producer),
        )
        for block_id, addr, kind, text, digest in (
            (101, "p1/1", "heading", "Termination", b"\x00" * 16),
            (104, "p1/104", "paragraph", "A clause the new parse found.", b"\x01" * 16),
        ):
            conn.execute(
                "INSERT INTO block(block_id, doc_ord, gen, page, addr, cite, ord, kind, layer, "
                "                  text, content_digest, os_kind, producer_id, method, trust, "
                "                  quote, origin_operator, origin_driver, driver_schema_v, "
                "                  restriction_bits, state) "
                "VALUES(?, 1, 2, 1, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 2, 4, 'op.parse', 'drv', 1, "
                "       0, 0)",
                (
                    block_id,
                    addr,
                    f"d1#{block_id}",
                    1 if kind == "heading" else block_id,
                    _code(conn, "kind", kind),
                    _code(conn, "layer", "body"),
                    text,
                    digest,
                    _code(conn, "origin_span_kind", "none"),
                    producer,
                    native,
                ),
            )
        conn.execute(
            "INSERT INTO diag(doc_ord, gen, code, severity, component, message, detail, fatal) "
            "VALUES(1, 2, 'OW_REBIND_UNEXPLAINED', 'error', 'omniweave_core.store.doc', "
            "       'generation 2 is quarantined', ?, 1)",
            (json.dumps({"threshold": threshold}),),
        )
        conn.commit()
    finally:
        conn.close()


def _store(root: Path) -> Path:
    return root / ".omniweave" / "index.owstore"


@pytest.fixture
def project(tmp_path: Path, seeded_store: Any) -> Path:
    (tmp_path / "omniweave.toml").write_text(PROJECT, encoding="utf-8")
    _stage(seeded_store(_store(tmp_path)))
    return tmp_path


def _run(argv: Sequence[str], cwd: Path) -> tuple[int, str, str]:
    out, err = io.StringIO(), io.StringIO()
    code = verb.main(["doc", "diff", *argv], env={}, cwd=cwd, stdout=out, stderr=err)
    return code, out.getvalue(), err.getvalue()


def test_render_json_is_rebind_reports_ten_fields_after_schema(project: Path) -> None:
    code, out, err = _run(["d1#1", "--render", "json"], project)
    assert (code, err) == (0, "")
    document = json.loads(out)
    assert list(document) == [
        "schema",
        "corpus",
        "doc_ord",
        "from_gen",
        "to_gen",
        "carried",
        "revised",
        "created",
        "retired",
        "match_rate_by_page",
        "quarantined",
        "threshold",
    ]
    assert (document["from_gen"], document["to_gen"], document["quarantined"]) == (1, 2, True)
    counts = (document["carried"], document["revised"], document["created"], document["retired"])
    assert counts == (1, 0, 1, 2)
    assert document["threshold"] == THRESHOLD, "the threshold the quarantine recorded"
    #  Empty, and rightly: `rebind()` rates pages over head blocks that have a parent (03:1367),
    #  and every block `seeded_store` writes is parentless. `_diff_text`'s test covers the pages.
    assert document["match_rate_by_page"] == {}


def test_the_recorded_threshold_is_reported_and_staged_is_quarantined_whatever_the_rate(
    tmp_path: Path, seeded_store: Any
) -> None:
    """`quarantined` is *"not committed"*: generation 2 is not the head, although its rate of 1/3
    clears the 0.2 this quarantine recorded. `end_doc()` also quarantines what `owcheck` fails."""
    (tmp_path / "omniweave.toml").write_text(PROJECT, encoding="utf-8")
    _stage(seeded_store(_store(tmp_path)), threshold=0.2)
    document = json.loads(_run(["d1#1", "--render", "json"], tmp_path)[1])
    assert (document["threshold"], document["quarantined"]) == (0.2, True)


def test_the_text_render_says_what_moved_and_that_the_newer_generation_is_not_the_head(
    project: Path,
) -> None:
    code, out, err = _run(["d1#1"], project)
    assert (code, err) == (0, "")
    assert out.splitlines() == [
        "d1  generation 1 -> 2  quarantined, not committed",
        "  carried 1  revised 0  created 1  retired 2",
        "  matched 0.33 of the older generation, threshold 0.90",
    ]


def test_the_text_render_lists_the_pages_below_the_threshold_and_no_other() -> None:
    document = {
        "doc_ord": 7,
        "from_gen": 3,
        "to_gen": 4,
        "carried": 9,
        "revised": 1,
        "created": 2,
        "retired": 1,
        "match_rate_by_page": {"0": 1.0, "4": 0.5, "5": 0.9},
        "quarantined": False,
        "threshold": 0.9,
    }
    assert verb._diff_text(document, 0.9) == [
        "d7  generation 3 -> 4  committed",
        "  carried 9  revised 1  created 2  retired 1",
        "  matched 0.90 of the older generation, threshold 0.90",
        "  page 4  matched 0.50",
    ]


def test_a_document_is_named_by_any_ref_ow_open_resolves(project: Path) -> None:
    by_cite = _run(["d1#2", "--render", "json"], project)[1]
    assert _run(["contract.pdf", "--render", "json"], project)[1] == by_cite


def test_diffing_writes_nothing(project: Path) -> None:
    def state() -> list[Any]:
        conn = sqlite3.connect(_store(project))
        try:
            return [
                conn.execute(sql).fetchall()
                for sql in (
                    "SELECT block_id, gen, state FROM block ORDER BY block_id",
                    "SELECT gen FROM doc",
                    "SELECT count(*) FROM block_history",
                    "SELECT count(*) FROM diag",
                )
            ]
        finally:
            conn.close()

    before = state()
    assert _run(["d1#1"], project)[0] == 0
    assert state() == before


def test_a_head_with_nothing_staged_beside_it_has_no_pair_exit_2(
    tmp_path: Path, seeded_store: Any
) -> None:
    (tmp_path / "omniweave.toml").write_text(PROJECT, encoding="utf-8")
    seeded_store(_store(tmp_path))
    code, out, err = _run(["d1#1"], tmp_path)
    assert (code, out) == (2, "")
    assert "live rows at generation 1 only" in err


@pytest.mark.parametrize(
    ("flags", "exit_code", "said"),
    [
        (["--from-gen", "2", "--to-gen", "1"], 1, "--from-gen 2 must be older than --to-gen 1"),
        (["--to-gen", "7"], 2, "no live row at generation 7"),
        (["--from-gen", "1", "--to-gen", "2"], 0, ""),
    ],
)
def test_explicit_generations_are_checked_against_the_rows(
    project: Path, flags: list[str], exit_code: int, said: str
) -> None:
    code, _, err = _run(["d1#1", *flags], project)
    assert code == exit_code
    assert said in err


def test_a_ref_that_names_nothing_is_exit_2(project: Path) -> None:
    code, _, err = _run(["d1#999"], project)
    assert code == 2
    assert err


@pytest.mark.parametrize(
    ("flags", "named"),
    [
        (["--quiet"], "--quiet"),
        (["--render", "jsonl"], "--render jsonl"),
        (["--render", "rows"], "--render rows"),
    ],
)
def test_a_parsed_flag_this_build_cannot_serve_is_refused_by_name(
    project: Path, flags: list[str], named: str
) -> None:
    code, out, err = _run(["d1#1", *flags], project)
    assert (code, out) == (1, "")
    assert f"{named} is parsed and not served by ow doc diff" in err


def test_an_error_under_render_json_is_the_error_object_on_stdout(
    tmp_path: Path, seeded_store: Any
) -> None:
    (tmp_path / "omniweave.toml").write_text(PROJECT, encoding="utf-8")
    seeded_store(_store(tmp_path))
    code, out, err = _run(["d1#1", "--render", "json"], tmp_path)
    assert (code, err) == (2, "")
    assert list(json.loads(out)) == ["schema", "error"]
