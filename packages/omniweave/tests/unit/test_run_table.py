"""`derive.entity.table` in a real run: a parsed CSV's rows become entities and claims. **D681.**

The office parse writes a CSV as one table with a header row, each cell a container holding a
paragraph. Before D681 the view gave no paragraph its cell's position, so no table rule could have
fired on it; this is the run that shows one does.
"""

from __future__ import annotations

from pathlib import Path

from omniweave_core.config import load
from test_run_parse import OPT_IN, PROJECT, _project, _rows, _run


def test_a_csvs_rows_are_entities_and_its_cells_are_claims(tmp_path: Path) -> None:
    store, config = _project(tmp_path, ("rows.csv",))
    report = _run(tmp_path, store, config)
    assert report.status == "ok"
    assert any(
        line.startswith("  derive    derive.entity.table: 1 document(s)") for line in report.lines()
    )
    entities = _rows(store, "SELECT scope <> 0, etype, key FROM entity ORDER BY key")
    assert entities == [(1, "unknown", "east"), (1, "unknown", "north"), (1, "unknown", "south")]
    claims = _rows(
        store,
        "SELECT s.key, c.predicate, c.object_literal, c.object_datatype, c.claim_type, c.status "
        "FROM claim c JOIN entity s ON s.entity_id = c.subject_entity ORDER BY 1, 2",
    )
    assert claims == [
        ("east", "units", "0", "xsd:decimal", "attribute", "asserted"),
        ("north", "note", "steady", "string", "attribute", "asserted"),
        ("north", "units", "17", "xsd:decimal", "attribute", "asserted"),
        ("south", "note", "a note, with a comma", "string", "attribute", "asserted"),
        ("south", "units", "4", "xsd:decimal", "attribute", "asserted"),
    ]
    assert _rows(store, "SELECT count(*) FROM quarantine") == [(0,)]
    [(status,)] = _rows(
        store, "SELECT DISTINCT status FROM derive_run WHERE pass_id = 'derive.entity.table'"
    )
    assert status == "ok"


def test_a_re_parse_keeps_one_copy_of_every_claim_and_mention(tmp_path: Path) -> None:
    """D681. A driver change re-parses the CSV at generation 2; the segmenter keeps its Segment, so
    the table Pass runs again on the same `segment_id` and its earlier run's claims and mentions
    are retired as `pass_replaced` (08 section 4.8, owner-scoped) rather than left beside the new
    ones. GR8 found the duplicate: every table claim twice after its driver step."""
    store, config = _project(tmp_path, ("rows.csv",))
    _run(tmp_path, store, config)
    claims = "SELECT predicate, object_literal FROM claim ORDER BY 1, 2"
    mentions = "SELECT surface FROM mention ORDER BY 1"
    first = (_rows(store, claims), _rows(store, mentions))
    (tmp_path / "omniweave.toml").write_text(
        PROJECT + OPT_IN + '[drivers."parse.office.anydoc".config]\nmax_asset_bytes = 33554431\n',
        encoding="utf-8",
    )
    moved = load(cwd=tmp_path, env={"OMNIWEAVE_HOME": str(tmp_path / "owhome")})
    assert _run(tmp_path, store, moved).reparsed == 1
    assert _rows(store, "SELECT gen FROM doc") == [(2,)]
    assert (_rows(store, claims), _rows(store, mentions)) == first
    history = "SELECT kind, reason, count(*) FROM graph_history GROUP BY 1, 2 ORDER BY 1"
    assert _rows(store, history) == [("claim", "pass_replaced", 5), ("mention", "pass_replaced", 3)]
