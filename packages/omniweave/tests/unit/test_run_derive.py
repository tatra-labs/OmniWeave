"""D668: the free Passes' plan, the rows segmentation enqueues for them, and the registry row.

The run end to end is `tests/conform/test_defterm_at_ingest.py`'s; this is each piece against the
real catalog, the real resolver and a real store whose CHECKs judge every row.
"""

from __future__ import annotations

import json
import sqlite3  # noqa: TID251 -- the assertions read the rows the statements wrote.
from dataclasses import replace
from pathlib import Path
from typing import Any, cast

from omniweave.run.dispatch import dispatch_key
from omniweave.run.operators.derive import (
    DERIVE_PRIORITY,
    FREE_PASSES,
    DerivePlan,
    is_derive,
)
from omniweave.run.operators.parse import DeriveCount, ParseTally
from omniweave.run.operators.segment import SEGMENTER_ID, SegmentPlan
from omniweave.run.routing import resolve_policy
from omniweave_core.config import load
from omniweave_core.discovery import catalog
from omniweave_core.model.enums import Method
from omniweave_core.operator import Roots, RunContext
from omniweave_core.store import migrate
from omniweave_core.store import sqlite as ow
from omniweave_core.store.items import ITEM_LANES, register_pass
from omniweave_ports.types import UnitRef

DEFTERM = "derive.anchor.defterm"
XREF = "derive.xref.pattern"
NATIVE = "derive.anchor.native"
LINKS = "derive.xref.native"
UNIT = UnitRef(uri="file:///docs/a.md", part="", content_sha256="ab" * 32, byte_len=10)
OPEN = "[drivers]\nallow_unattested = true\nrequire_lock = false\ninproc = []\n"


def _ctx() -> RunContext:
    return RunContext(
        run_id="r_0000000000000000000000000",
        generation=3,
        trigger="cli",
        roots=Roots(source=Path(), output=Path(), cache=Path()),
        config_digest="c" * 64,
        semantic_digest="s" * 64,
        policy_digest="p" * 64,
        pricebook_digest="b" * 64,
        catalog_digest="k" * 64,
        limits=cast("Any", object()),
        admission=cast("Any", object()),
        services=cast("Any", object()),
        budget=cast("Any", object()),
        cancel=cast("Any", object()),
        clock=cast("Any", object()),
        events=cast("Any", object()),
    )


def _policy(tmp_path: Path, body: str = OPEN) -> Any:
    (tmp_path / "omniweave.toml").write_text(body, encoding="utf-8")
    return resolve_policy(load(cwd=tmp_path, env={}))


def _store(tmp_path: Path) -> Path:
    store = tmp_path / "s.owstore"
    connection = ow.connect(store)
    try:
        migrate.apply_pending(connection, now_ns=1)
        connection.execute(
            "INSERT INTO unit(unit_uri, state, trust_class, last_seen_gen) "
            "VALUES(?, 'settled', 'internal', 1)",
            (UNIT.uri,),
        )
    finally:
        connection.close()
    return store


def _rows(store: Path, sql: str) -> list[tuple[Any, ...]]:
    raw = sqlite3.connect(store)
    try:
        return raw.execute(sql).fetchall()
    finally:
        raw.close()


def test_each_plan_is_its_own_pinned_driver_and_never_another_derive_driver(
    tmp_path: Path,
) -> None:
    """`pinned` filters nothing: with two derive/1 drivers installed, each plan picks by id."""
    policy = _policy(tmp_path)
    derives, why = DerivePlan.of(catalog(), policy, _ctx())
    assert derives is not None, why
    assert why == ""
    assert [c.card.identity.id for c in derives.passes] == [NATIVE, LINKS, DEFTERM, XREF]
    segments, why = SegmentPlan.of(catalog(), policy, _ctx())
    assert segments is not None, why
    assert segments.candidate.card.identity.id == SEGMENTER_ID


def test_a_pass_resolve_refuses_is_no_plan_and_a_reason_naming_it(tmp_path: Path) -> None:
    derives, why = DerivePlan.of(catalog(), _policy(tmp_path, "[drivers]\n"), _ctx())
    assert derives is None
    assert f"{DEFTERM}: not_in_lockfile" in why, why


def test_each_enqueued_row_is_its_pass_with_its_driver_and_no_decision(
    tmp_path: Path,
) -> None:
    derives, _ = DerivePlan.of(catalog(), _policy(tmp_path), _ctx())
    assert derives is not None
    store = _store(tmp_path)
    connection = ow.connect(store)
    try:
        assert derives.enqueue(connection, UNIT) == 4
        assert derives.enqueue(connection, UNIT) == 0, "a resumed run enqueues nothing twice"
    finally:
        connection.close()
    assert _rows(
        store,
        "SELECT operator, op_version, driver, decision_id, cost_class, status, priority, "
        "unit_part, dispatch_key FROM work ORDER BY operator",
    ) == [
        (
            candidate.card.identity.id,
            1,
            candidate.card.identity.id,
            None,
            "free",
            "pending",
            DERIVE_PRIORITY,
            "",
            dispatch_key(
                candidate.card.identity.id,
                candidate.config_digest,
                str(candidate.isolation_granted),
            ),
        )
        for candidate in sorted(derives.passes, key=lambda c: c.card.identity.id)
    ]


def test_the_registry_row_is_read_off_the_card_and_keeps_an_operators_enabled(
    tmp_path: Path,
) -> None:
    card = catalog().cards.get(DEFTERM)
    assert card is not None
    store = _store(tmp_path)
    connection = ow.connect(store)
    try:
        register_pass(connection, card)
        connection.execute("UPDATE derive_pass SET enabled = 0, phase = 99")
        register_pass(connection, card)
    finally:
        connection.close()
    [(port, cost, rank, phase, lanes, granularity, sha, version, enabled)] = _rows(
        store,
        "SELECT port, cost_class, cost_rank, phase, lanes, granularity, card_sha256, "
        "schema_version, enabled FROM derive_pass",
    )
    assert (port, cost, rank, phase, granularity, sha, version, enabled) == (
        "derive/1",
        "free",
        0,
        30,
        "document",
        card.card_sha256,
        1,
        0,
    )
    assert json.loads(lanes) == ["anchor", "entity"]


def test_items_map_to_the_lanes_they_serve() -> None:
    assert {ITEM_LANES[i] for i in ("entity", "alias", "mention", "edge")} == {"entity"}
    assert (ITEM_LANES["anchor"], ITEM_LANES["xref"], ITEM_LANES["claim"]) == (
        "anchor",
        "xref",
        "claim",
    )
    assert "segment" not in ITEM_LANES


def test_which_rows_are_a_free_pass_and_which_method_each_pass_has() -> None:
    assert is_derive("derive.anchor")
    assert not is_derive("derive.segment")
    assert not is_derive("parse.text")
    assert FREE_PASSES == {
        NATIVE: Method.NATIVE_XML,
        LINKS: Method.NATIVE_XML,
        DEFTERM: Method.HEURISTIC,
        XREF: Method.HEURISTIC,
    }


def test_the_report_says_what_each_pass_did_and_why_one_did_not() -> None:
    tally = ParseTally()
    tally.parsed["parse.text.builtin"] = 2
    tally.segmented = 2
    tally.derived[DEFTERM] = DeriveCount(documents=2, runs=3, items=11, quarantined=1)
    tally.derive_failed[f"{DEFTERM} driver_bug"] = 1
    tally.derive_skipped = "derive.x.y: not installed"
    lines = tally.lines()
    assert (
        f"  derive    {DEFTERM}: 2 document(s), 3 Segment run(s), 11 item(s) written, 1 quarantined"
    ) in lines
    assert f"  derive    1 failed ({DEFTERM} driver_bug 1)" in lines
    assert "  derive    not enqueued: derive.x.y: not installed" in lines
    quiet = ParseTally()
    quiet.parsed["parse.text.builtin"] = 1
    quiet.derive_skipped = "derive.x.y: not installed"
    assert not any("derive" in line for line in quiet.lines()), "nothing segmented, nothing to say"


def test_a_refused_pass_is_never_replaced_by_another_derive_driver_that_resolved(
    tmp_path: Path,
) -> None:
    """Lock only the segmenter: it resolves, defterm does not, and no plan borrows the segmenter."""
    policy = replace(_policy(tmp_path), require_lock=True, locked_ids=frozenset({SEGMENTER_ID}))
    segments, _ = SegmentPlan.of(catalog(), policy, _ctx())
    assert segments is not None, "the segmenter is locked and resolves"
    derives, why = DerivePlan.of(catalog(), policy, _ctx())
    assert derives is None
    assert f"{DEFTERM}: " in why, why
