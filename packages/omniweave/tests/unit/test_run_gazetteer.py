"""`op.lexicon` and `derive.entity.gazetteer` in a real run: a table's parties in prose. **D683.**

A CSV with a `Party` column gives the corpus two `org` entities (`derive.entity.table`, D681); a
Markdown memo names them in running text. One `ow ingest` builds the lexicon after the drain and
runs the gazetteer over both documents in the same run.
"""

from __future__ import annotations

import json
import sqlite3  # noqa: TID251 -- the filters are read against the store a run wrote.
from pathlib import Path

import pytest
from omniweave_core.config import Config
from omniweave_core.store import lexicon
from omniweave_core.store.lexicon import EMPTY
from test_run_parse import _project, _rows, _run

GAZETTEER = "derive.entity.gazetteer"
PARTIES = "Party,Role\nAcme Holdings Ltd,Seller\nBeta Corp,Buyer\n"
MEMO = (
    "# Memo\n\nAcme Holdings, Ltd. will deliver the goods to Beta Corp in June.\n\n"
    "Gamma Inc is not a party, and acmes are not Acme Holdings Ltd.\n"
)
OWN = (
    "SELECT e.key, m.surface FROM mention m JOIN derive_run r ON r.run_id = m.run_id"
    " JOIN entity e ON e.entity_id = m.entity_id JOIN block b ON b.block_id = m.block_id"
    " JOIN doc d ON d.doc_ord = b.doc_ord"
    " WHERE r.pass_id = 'derive.entity.gazetteer' AND m.state = 0 AND d.uri LIKE '%memo.md'"
    " ORDER BY m.mention_id"
)


def _corpus(tmp_path: Path, **files: str) -> tuple[Path, Config]:
    store, config = _project(tmp_path, ())
    for name, text in files.items():
        (tmp_path / "docs" / name.replace("_", ".")).write_text(text, encoding="utf-8")
    return store, config


def test_one_ingest_finds_the_tables_parties_in_the_memo(tmp_path: Path) -> None:
    store, config = _corpus(tmp_path, parties_csv=PARTIES, memo_md=MEMO)
    report = _run(tmp_path, store, config)
    assert report.status == "ok", report.lines()
    shown = report.lines()
    assert any(
        line.startswith("  derive    derive.entity.gazetteer: 2 document(s)") for line in shown
    ), shown
    lexicon_line = (
        "  lexicon   2 of 2 name(s); moved, 0 gazetteer row(s) re-opened; "
        "2 document(s) queued for the gazetteer"
    )
    assert lexicon_line in shown, shown
    assert _rows(store, OWN) == [
        ("acme_holdings_ltd", "Acme Holdings, Ltd"),
        ("beta_corp", "Beta Corp"),
        ("acme_holdings_ltd", "Acme Holdings Ltd"),
    ]
    #  No new entity: every mention binds to one the table Pass minted.
    assert _rows(store, "SELECT count(*), sum(scope = 0) FROM entity WHERE etype = 'org'") == [
        (2, 2)
    ]
    [(digest,)] = _rows(store, "SELECT v FROM index_state WHERE k = 'lexicon'")
    assert _rows(store, "SELECT DISTINCT kind, key, digest FROM dep") == [
        ("name", "lexicon", digest)
    ]
    assert _rows(store, "SELECT count(*) FROM dep JOIN work w ON w.id = dep.dependent_id"
                        " WHERE w.operator = 'derive.entity.gazetteer'") == [(2,)]  # fmt: skip
    assert _rows(store, "SELECT count(*) FROM quarantine") == [(0,)]

    again = _run(tmp_path, store, config)
    assert again.lexicon is not None
    assert (again.lexicon.moved, again.lexicon.drain, again.lexicon.digest) == (
        False,
        False,
        digest,
    )
    assert len(_rows(store, OWN)) == 3, "a second build is the first's: nothing re-ran"


def test_a_new_party_moves_the_lexicon_and_re_runs_the_gazetteer_once(tmp_path: Path) -> None:
    store, config = _corpus(tmp_path, parties_csv=PARTIES, memo_md=MEMO)
    _run(tmp_path, store, config)
    more = "Company,Since\nGamma Inc,2019\nDelta LLC,2020\n"  # one data row is detected as text
    (tmp_path / "docs" / "more.csv").write_text(more, encoding="utf-8")
    report = _run(tmp_path, store, config)
    assert report.status == "ok", report.lines()
    assert report.lexicon is not None
    assert (report.lexicon.names, report.lexicon.moved) == (4, True)
    assert report.lexicon.reopened == 2, "the two documents the gazetteer had read"
    assert report.lexicon.enqueued == 1, "the new CSV"
    assert _rows(store, OWN) == [
        ("acme_holdings_ltd", "Acme Holdings, Ltd"),
        ("beta_corp", "Beta Corp"),
        ("gamma_inc", "Gamma Inc"),
        ("acme_holdings_ltd", "Acme Holdings Ltd"),
    ], "the earlier run's three mentions were replaced, not kept beside the new four"
    [(digest,)] = _rows(store, "SELECT v FROM index_state WHERE k = 'lexicon'")
    assert _rows(store, "SELECT DISTINCT digest FROM dep") == [(digest,)]
    attempts = "SELECT DISTINCT attempts_total FROM work WHERE operator = 'derive.entity.gazetteer'"
    assert _rows(store, attempts) == [(1,)], "a re-open is not a retry (D683)"
    #  06 section 10.2's row: the rebuilt lexicon's reader rows are deleted, historied first.
    history = "SELECT kind, reason, count(*) FROM graph_history GROUP BY 1, 2"
    assert _rows(store, history) == [("mention", "pass_replaced", 5)], "memo 3, parties.csv 2"
    runs = (
        "SELECT count(*), count(DISTINCT segment_id) FROM derive_run"
        " WHERE pass_id = 'derive.entity.gazetteer'"
    )
    assert _rows(store, runs) == [(3, 3)], "one run per Segment: the earlier two left"


def test_a_name_in_most_documents_is_a_template_and_stays_out(tmp_path: Path) -> None:
    """06:1203 at two documents of three: `Acme` is defined in both CSVs."""
    acme = "Party,Role\nAcme Holdings Ltd,Seller\n"
    store, config = _corpus(
        tmp_path, a_csv=acme + "Delta LLC,Agent\n", b_csv=acme + "Beta Corp,Buyer\n", memo_md=MEMO
    )
    report = _run(tmp_path, store, config)
    assert report.lexicon is not None
    assert (report.lexicon.names, dict(report.lexicon.dropped)) == (2, {"template": 1})
    assert _rows(store, OWN) == [("beta_corp", "Beta Corp")]


def test_a_corpus_with_no_corpus_entity_reads_the_empty_lexicon(tmp_path: Path) -> None:
    """06:913's `empty lexicon`: the gazetteer still runs, and says why it found nothing."""
    store, config = _corpus(tmp_path, memo_md=MEMO)
    report = _run(tmp_path, store, config)
    assert report.status == "ok", report.lines()
    assert report.lexicon is not None
    assert (report.lexicon.names, report.lexicon.moved, report.lexicon.enqueued) == (0, False, 1)
    import hashlib  # noqa: PLC0415

    assert report.lexicon.digest == hashlib.sha256(EMPTY).hexdigest()
    reasons = _rows(
        store,
        "SELECT DISTINCT c.empty_reason FROM derive_cover c"
        " JOIN derive_run r ON r.run_id = c.run_id"
        " WHERE r.pass_id = 'derive.entity.gazetteer'",
    )
    assert reasons == [("empty lexicon",)]


MORE = "Company,Since\nGamma Inc,2019\nDelta LLC,2020\n"
FOUND = (
    "SELECT d.uri, e.key, m.surface, m.ts_a, m.ts_b FROM mention m"
    " JOIN derive_run r ON r.run_id = m.run_id JOIN entity e ON e.entity_id = m.entity_id"
    " JOIN block b ON b.block_id = m.block_id JOIN doc d ON d.doc_ord = b.doc_ord"
    " WHERE r.pass_id = 'derive.entity.gazetteer' AND m.state = 0"
)


def _found(store: Path) -> list[tuple[object, ...]]:
    return sorted((Path(str(uri)).name, *rest) for uri, *rest in _rows(store, FOUND))


def test_an_incremental_build_finds_what_a_full_one_does(tmp_path: Path) -> None:
    """INV-18 for the gazetteer, which GR8 cannot see: `canonical_projection()` holds no mention.

    The same-run drain (D683) is what makes one ingest of the third file land where a single
    ingest of all three does."""
    (tmp_path / "step").mkdir()
    (tmp_path / "full").mkdir()
    step, config = _corpus(tmp_path / "step", parties_csv=PARTIES, memo_md=MEMO)
    _run(tmp_path / "step", step, config)
    (tmp_path / "step" / "docs" / "more.csv").write_text(MORE, encoding="utf-8")
    _run(tmp_path / "step", step, config)
    whole, whole_config = _corpus(
        tmp_path / "full", parties_csv=PARTIES, memo_md=MEMO, more_csv=MORE
    )
    _run(tmp_path / "full", whole, whole_config)
    found = _found(step)
    assert ("memo.md", "gamma_inc", "Gamma Inc") in [row[:3] for row in found]
    assert found == _found(whole)
    lexicon_digest = "SELECT v FROM index_state WHERE k = 'lexicon'"
    assert _rows(step, lexicon_digest) == _rows(whole, lexicon_digest)


def test_a_crashed_gazetteer_batch_leaves_the_run_partial(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """D683: a batch that crashed left its rows `claimed`, and the run used to say `ok`."""
    from omniweave.run.operators import derive  # noqa: PLC0415

    def crash(_self: object) -> str:
        raise RuntimeError("the lexicon could not be read")

    monkeypatch.setattr(derive.DeriveOperator, "_lexicon", crash)
    store, config = _corpus(tmp_path, parties_csv=PARTIES, memo_md=MEMO)
    report = _run(tmp_path, store, config)
    assert report.status == "partial", report.lines()
    claimed = "SELECT DISTINCT status FROM work WHERE operator = 'derive.entity.gazetteer'"
    assert _rows(store, claimed) == [("claimed",)]


@pytest.fixture(scope="module")
def ingested(tmp_path_factory: pytest.TempPathFactory) -> Path:
    tmp_path = tmp_path_factory.mktemp("lexicon")
    store, config = _corpus(tmp_path, parties_csv=PARTIES, memo_md=MEMO)
    assert _run(tmp_path, store, config).status == "ok"
    return store


def _build(store: Path, *edits: str) -> lexicon.Built:
    """`lexicon.build` over a copy of the run's store with `edits` applied, never committed."""
    connection = sqlite3.connect(store)
    try:
        for sql in edits:
            connection.execute(sql)
        return lexicon.build(connection)
    finally:
        connection.rollback()
        connection.close()


def _names(built: lexicon.Built) -> list[str]:
    return [json.loads(line)["name"] for line in built.body.splitlines()[1:]]


def test_the_build_is_the_corpus_entities_names(ingested: Path) -> None:
    built = _build(ingested)
    assert (_names(built), built.candidates, built.truncated) == (
        ["acme_holdings_ltd", "beta_corp"],
        2,
        False,
    )
    assert _build(ingested).body == built.body, "deterministic: one store, one artefact"


def test_an_untrusted_alias_seen_in_one_document_stays_out(ingested: Path) -> None:
    """06:1200 and ruling 4: every alias row of the pair carries the bit, and one document."""
    built = _build(ingested, "UPDATE entity_alias SET taint = 1 WHERE name_norm = 'beta_corp'")
    assert (_names(built), dict(built.dropped)) == (["acme_holdings_ltd"], {"untrusted": 1})


@pytest.mark.parametrize(
    "edit",
    [
        "UPDATE entity SET scope = 1 WHERE key = 'beta_corp'",
        "UPDATE entity SET state = 1 WHERE key = 'beta_corp'",
        "UPDATE entity SET state = 2 WHERE key = 'beta_corp'",
    ],
    ids=["document_scoped", "overloaded", "retired"],
)
def test_only_live_corpus_entities_are_targets(ingested: Path, edit: str) -> None:
    """Ruling 1: a document-scoped proposal would mint a new entity in the reader's document."""
    built = _build(ingested, edit)
    assert (_names(built), built.candidates) == (["acme_holdings_ltd"], 1)


def test_a_name_whose_evidence_left_stays_out(ingested: Path) -> None:
    """Ruling 2: the gazetteer's own mentions are not evidence; with the table's gone, none is."""
    built = _build(
        ingested,
        "UPDATE mention SET state = 1 WHERE entity_id = (SELECT entity_id FROM entity"
        " WHERE key = 'beta_corp') AND run_id IN (SELECT run_id FROM derive_run"
        " WHERE pass_id = 'derive.entity.table')",
    )
    assert (_names(built), dict(built.dropped)) == (["acme_holdings_ltd"], {"no_evidence": 1})


def test_a_short_name_is_noise(ingested: Path) -> None:
    built = _build(
        ingested, "UPDATE entity_alias SET name_norm = 'bet' WHERE name_norm = 'beta_corp'"
    )
    assert (_names(built), built.candidates) == (["acme_holdings_ltd"], 1)


def test_past_the_cap_the_longest_names_of_the_most_documents_stay(
    ingested: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """06:1211's order, `(doc_count DESC, LENGTH(name_norm) DESC, name_norm)`, and the flag."""
    monkeypatch.setattr(lexicon, "MAX_LEXICON_ENTRIES", 1)
    built = _build(ingested)
    assert (_names(built), built.truncated, built.names) == (["acme_holdings_ltd"], True, 1)
    assert json.loads(built.body.splitlines()[0])["truncated"] is True


def test_one_live_document_is_no_template(ingested: Path) -> None:
    """Ruling 3: with the memo retired the CSV is the whole corpus, and a name in all of one
    document is not a template across a corpus."""
    built = _build(
        ingested,
        "UPDATE doc SET x = json_set(x, '$.ow.retired', 1) WHERE uri LIKE '%memo.md'",
    )
    assert (_names(built), dict(built.dropped)) == (["acme_holdings_ltd", "beta_corp"], {})
