"""The LLM band's manifest, its decision and its `band:` row. **D728.**

Over a store a real ingest wrote, whose two Northwind spellings score 88.24 across documents: the
one pair `op.resolve` hands on (D727), and the rows 05:1103 writes *"BEFORE anything runs"*.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3  # noqa: TID251 -- the assertions read and edit the store a run wrote.
from dataclasses import replace
from typing import TYPE_CHECKING, Any

import pytest
from omniweave.graph.resolve import Band
from omniweave.route.ledger import read_set_from
from omniweave.route.rung import Rung
from omniweave.run.dispatch import dispatch_key
from omniweave.run.operators.band import (
    BAND_PASS,
    BATCHES_KEY,
    HIGH_KEY,
    LLM_BATCH,
    LOW_KEY,
    MAX_ALIASES,
    PAIRS_KEY,
    RULE_ID,
    RULE_ORIGIN,
    Manifest,
    enqueue_band,
    manifest,
    ordered,
    put_manifest,
)
from omniweave.run.operators.derive import MERGE_LLM, DerivePlan
from omniweave.run.routing import INGEST_HINTS_DIGEST, resolve_policy
from omniweave_core.blobs import BlobStore
from omniweave_core.config import SHIPPED_DRIVERS, load
from omniweave_core.discovery import catalog
from test_billed_selector import LLM, OPEN
from test_graph_resolve import NORTH_A, NORTH_B
from test_run_derive import _ctx
from test_run_parse import _project, _run

if TYPE_CHECKING:
    from pathlib import Path

ROWS = (
    "SELECT w.unit_uri, w.unit_part, w.operator, w.cost_class, w.status, w.priority, w.driver,"
    " w.dispatch_key, w.service, d.lane, d.rung, d.rule_id, d.rule_origin, d.cause, d.cost_class,"
    " d.admission, d.est_spend, d.content_sha256, d.hints_digest, d.decision_id, d.evidence_digest"
    " FROM work AS w JOIN route_decision AS d ON d.decision_id = w.decision_id"
    " WHERE w.operator = 'derive.merge.llm' ORDER BY w.unit_part"
)


@pytest.fixture(scope="module")
def banded(tmp_path_factory: pytest.TempPathFactory) -> tuple[Path, tuple[Band, ...]]:
    tmp_path = tmp_path_factory.mktemp("band")
    store, config = _project(tmp_path, ())
    (tmp_path / "docs" / "a.csv").write_text(NORTH_A, encoding="utf-8")
    (tmp_path / "docs" / "b.csv").write_text(NORTH_B, encoding="utf-8")
    report = _run(tmp_path, store, config)
    assert report.status == "ok", report.lines()
    assert report.resolved is not None and len(report.resolved.band) == 1
    return store, report.resolved.band


def _policy(tmp_path: Path, *drivers: str) -> Any:
    classes = ["free", "local_compute", "billed_api"]
    (tmp_path / "omniweave.toml").write_text(
        OPEN
        + f"enabled = {[*SHIPPED_DRIVERS, *drivers]!r}\n[drivers.cost]\nallow_classes = "
        f"{classes!r}\n".replace("'", '"'),
        encoding="utf-8",
    )
    return resolve_policy(load(cwd=tmp_path, env={}), offline=False)


@pytest.fixture(scope="module")
def plan(tmp_path_factory: pytest.TempPathFactory) -> DerivePlan:
    policy = _policy(tmp_path_factory.mktemp("policy"), MERGE_LLM)
    derives, why = DerivePlan.of(catalog(), policy, _ctx(), enable=(MERGE_LLM,))
    assert derives is not None and derives.merge is not None, why
    return derives


def _ids(connection: sqlite3.Connection) -> dict[str, int]:
    return {str(k): int(e) for e, k in connection.execute("SELECT entity_id, key FROM entity")}


def _manifest(store: Path, band: tuple[Band, ...]) -> Manifest:
    connection = sqlite3.connect(store)
    try:
        found = manifest(connection, band)
    finally:
        connection.close()
    assert found is not None
    return found


# ---------------------------------------------------------------------------------------------
# the plan
# ---------------------------------------------------------------------------------------------


def test_the_plan_holds_the_merge_pass_only_when_both_lists_name_it(tmp_path: Path) -> None:
    """08:1977-1979, as D714 has it for the Segment Passes; the merge Pass is not one of those."""
    (tmp_path / "both").mkdir()
    both = _policy(tmp_path / "both", MERGE_LLM, LLM)
    derives, why = DerivePlan.of(catalog(), both, _ctx(), enable=(MERGE_LLM, LLM))
    assert derives is not None and derives.merge is not None and why == ""
    assert derives.merge.card.identity.id == MERGE_LLM
    assert [c.card.identity.id for c in derives.billed] == [LLM], "billed is the Segment Passes"
    (tmp_path / "off").mkdir()
    derives, why = DerivePlan.of(catalog(), _policy(tmp_path / "off"), _ctx(), enable=(MERGE_LLM,))
    assert derives is not None and derives.merge is None
    assert why == f"{MERGE_LLM}: [graph.passes] enable names it, [drivers] enabled does not"
    derives, why = DerivePlan.of(catalog(), both, _ctx())
    assert derives is not None and (derives.merge, why) == (None, "")


# ---------------------------------------------------------------------------------------------
# the manifest
# ---------------------------------------------------------------------------------------------


def test_a_side_is_what_the_documents_wrote_and_names_no_identifier(
    banded: tuple[Path, tuple[Band, ...]],
) -> None:
    """Ruling 1: the title, the type and the other names, an untrusted one-document name left out,
    at most MAX_ALIASES; no key, cite or id."""
    store, band = banded
    connection = sqlite3.connect(store)
    try:
        ids = _ids(connection)
        run = connection.execute("SELECT run_id FROM entity_alias LIMIT 1").fetchone()[0]
        names = [f"Northwind {n:02d}" for n in range(MAX_ALIASES + 2)]
        for name in names:
            connection.execute(
                "INSERT INTO entity_alias(entity_id, name_norm, surface, alias_kind, run_id, trust)"
                " VALUES(?, ?, ?, 'variant', ?, 2)",
                (ids["northwind_traders"], name.lower().replace(" ", "_"), name, run),
            )
        connection.execute(
            "INSERT INTO entity_alias(entity_id, name_norm, surface, alias_kind, run_id, trust,"
            " taint, doc_count) VALUES(?, 'acme', 'Acme', 'variant', ?, 2, ?, 1)",
            (ids["northwind_trading"], run, 1),
        )
        one = manifest(connection, band)
        assert one is not None
        [(left, right)] = one.sides
        assert left == {"surface": "Northwind Traders", "etype": "org",
                        "aliases": names[:MAX_ALIASES]}  # fmt: skip
        assert right == {"surface": "Northwind Trading", "etype": "org", "aliases": []}
        shown = json.dumps(one.sides)
        assert "northwind_traders" not in shown and "#" not in shown
    finally:
        connection.rollback()
        connection.close()


def test_the_witness_is_every_document_mentioning_an_end(
    banded: tuple[Path, tuple[Band, ...]],
) -> None:
    """Ruling 4, and ruling 5: the band is filed under the first."""
    store, band = banded
    one = _manifest(store, band)
    connection = sqlite3.connect(store)
    try:
        uris = dict(connection.execute(
            "SELECT substr(unit_uri, -5), unit_uri FROM unit WHERE unit_uri LIKE '%.csv'"
        ).fetchall())  # fmt: skip
    finally:
        connection.close()
    assert one.witness == (
        (uris["a.csv"], "", "northwind_traders"),
        (uris["b.csv"], "", "northwind_trading"),
    )
    assert one.anchor == uris["a.csv"]
    [(a, b, score)] = one.members
    assert (a, b) == (band[0].a, band[0].b)
    assert score == pytest.approx(88.24, abs=0.01)


def test_a_pair_whose_end_is_gone_is_dropped_and_no_band_is_none(
    banded: tuple[Path, tuple[Band, ...]],
) -> None:
    """An end retired between the resolve and the enqueue drops its pair, not the band."""
    store, band = banded
    one = _manifest(store, (*band, Band(a=band[0].a, b=99_999, score=80.0)))
    assert [(a, b) for a, b, _s in one.members] == [(band[0].a, band[0].b)]
    connection = sqlite3.connect(store)
    try:
        assert manifest(connection, ()) is None
    finally:
        connection.close()


def test_the_manifest_is_named_by_its_digest_and_kept_in_the_cas(
    banded: tuple[Path, tuple[Band, ...]], tmp_path: Path
) -> None:
    """Ruling 3."""
    store, band = banded
    one, again = _manifest(store, band), _manifest(store, band)
    assert one.sha256 == hashlib.sha256(one.body).hexdigest() == again.sha256
    assert one.name == f"band:{one.sha256[:16]}"
    (tmp_path / "cas").mkdir()
    cas = BlobStore(tmp_path / "cas")
    put_manifest(cas, one)
    with cas.open(one.sha256) as handle:
        assert handle.read() == one.body


def test_the_pairs_go_in_identity_order_thirty_to_a_batch() -> None:
    """Ruling 2."""
    identity = {n: (f"k{n:03d}", "org", n) for n in range(70)}
    band = [Band(a=n, b=n + 1, score=80.0) for n in range(61, 0, -1)]
    pairs = ordered(band, identity)
    assert [b.a for b in pairs] == list(range(1, 62))
    one = Manifest(
        members=tuple((b.a, b.b, b.score) for b in pairs),
        sides=(({}, {}),) * len(pairs),
        witness=(("u", "", "k"),),
    )
    assert [len(r) for r in one.batches] == [LLM_BATCH, LLM_BATCH, 1]
    assert [r.start for r in one.batches] == [0, 30, 60]


# ---------------------------------------------------------------------------------------------
# the rows
# ---------------------------------------------------------------------------------------------


def test_the_band_gets_one_decision_and_one_billed_row(
    banded: tuple[Path, tuple[Band, ...]], plan: DerivePlan
) -> None:
    """Rulings 5-8: filed under its first witness, decided on the entity lane at ENRICH."""
    store, band = banded
    connection = sqlite3.connect(store)
    try:
        one = manifest(connection, band)
        assert one is not None
        queued = enqueue_band(connection, plan, one, now_ms=7)
        assert (queued.pairs, queued.batches, queued.queued) == (1, 1, 1)
        assert queued.lines() == [f"  band      {BAND_PASS}: 1 pair(s) in 1 batch(es), 1 queued"]
        [row] = connection.execute(ROWS).fetchall()
        assert plan.merge is not None
        key = dispatch_key(BAND_PASS, plan.merge.config_digest, str(plan.merge.isolation_granted))
        assert row[:9] == (
            one.anchor, one.name, BAND_PASS, "billed_api", "pending", 100, BAND_PASS, key, "llm",
        )  # fmt: skip
        assert row[9:16] == (
            "entity", int(Rung.ENRICH), RULE_ID, RULE_ORIGIN, "1 pair(s) in [75, 92), 1 batch(es)",
            "billed_api", "admitted",
        )  # fmt: skip
        spend = json.loads(row[16])
        assert (spend["tokens_in"], spend["tokens_out"], spend["calls"]) == (2100, 240, 1)
        assert (row[17], row[18]) == (one.sha256, INGEST_HINTS_DIGEST)
        [(payload,)] = connection.execute(
            "SELECT payload FROM route_evidence WHERE evidence_digest = ?", (row[20],)
        ).fetchall()
        assert read_set_from(bytes(payload)) == {
            PAIRS_KEY: 1, BATCHES_KEY: 1, LOW_KEY: 75.0, HIGH_KEY: 92.0,
        }  # fmt: skip
        assert connection.execute(
            "SELECT decision_id FROM route_unit_decision WHERE unit_uri = ? AND unit_part = ?",
            (one.anchor, one.name),
        ).fetchall() == [(row[19],)]
        again = enqueue_band(connection, plan, manifest(connection, band), now_ms=8)
        assert (again.batches, again.queued) == (1, 0), "ruling 7: an unchanged band, no row"
    finally:
        connection.rollback()
        connection.close()


def test_the_estimate_is_the_cards_per_part_once_a_batch(
    banded: tuple[Path, tuple[Band, ...]], plan: DerivePlan
) -> None:
    """Ruling 6: thirty-one pairs are two batches, so two calls' worth."""
    store, band = banded
    connection = sqlite3.connect(store)
    try:
        one = manifest(connection, band)
        assert one is not None
        wide = replace(one, members=one.members * 31, sides=one.sides * 31)
        assert enqueue_band(connection, plan, wide, now_ms=7).batches == 2
        [row] = connection.execute(ROWS).fetchall()
        spend = json.loads(row[16])
        assert (spend["tokens_in"], spend["tokens_out"], spend["calls"]) == (4200, 480, 2)
        assert row[13] == "31 pair(s) in [75, 92), 2 batch(es)"
    finally:
        connection.rollback()
        connection.close()


def test_a_plan_without_the_merge_pass_writes_nothing(
    banded: tuple[Path, tuple[Band, ...]], plan: DerivePlan
) -> None:
    store, band = banded
    connection = sqlite3.connect(store)
    try:
        without = DerivePlan(plan.passes, plan.ctx, plan.billed)
        assert enqueue_band(connection, without, manifest(connection, band), now_ms=7).batches == 0
        assert enqueue_band(connection, plan, None, now_ms=7).batches == 0
        assert connection.execute(ROWS).fetchall() == []
    finally:
        connection.rollback()
        connection.close()
