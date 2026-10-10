"""A billed Pass in a real ingest: `derive.entity.llm` against a loopback model. **D716.**

Every link W8.8 has built so far, end to end:
- the selector hands each body Segment over (D714);
- each gets a decision and a `seg:` row (D715);
- the drain claims the row and reads the Segment's billed view (D709);
- the host attaches `[services.llm]` and grants it on the `INVOKE` (D713);
- the worker's `io.service()` reaches the model (D712);
- the driver's answer becomes frames (D710, D711);
- the sink writes them under the row's decision.

The model is a stub serving the two probe paths and chat completions, answering from the blocks it
was shown.
"""

from __future__ import annotations

import http.server
import json
import threading
import time
from types import SimpleNamespace
from typing import TYPE_CHECKING, Any, ClassVar, cast

import pytest
from omniweave_core.config import SHIPPED_DRIVERS, SHIPPED_PASSES, load
from test_run_parse import OPT_IN, PROJECT, _rows, _run

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

LLM = "derive.entity.llm"
MODEL = "qwen3:4b"
REV = "0123456789abcdef0123456789abcdef01234567"
MEMO = (
    "# Memo\n\nAcme Holdings will deliver the goods in June.\n\n"
    "## Payment\n\nBeta Corp pays on delivery.\n\n"
    "## Notes\n\nNothing else is agreed.\n"
)
NAMES = ("Acme Holdings", "Beta Corp")


class _Model(http.server.BaseHTTPRequestHandler):
    """A model server: `/health`, `/v1/models`, and an answer naming what the blocks name."""

    asked: ClassVar[list[dict[str, Any]]] = []
    delay_s: ClassVar[float] = 0.0

    def do_GET(self) -> None:
        if self.path == "/health":
            self._reply(200, {})
        elif self.path == "/v1/models":
            self._reply(200, {"data": [{"id": MODEL}]})
        else:
            self._reply(404, {})

    def do_POST(self) -> None:
        request = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        type(self).asked.append(request)
        time.sleep(type(self).delay_s)
        lane = request["response_format"]["json_schema"]["name"]
        answer = (
            {"claims": _claimed(request), "more_available": False}
            if lane == "owgraph_claim"
            else {"entities": _named(request), "relations": [], "more_available": False}
        )
        self._reply(
            200,
            {
                "choices": [{"message": {"role": "assistant", "content": json.dumps(answer)}}],
                "usage": {"prompt_tokens": 120, "completion_tokens": 30},
            },
        )

    def _reply(self, status: int, payload: dict[str, Any]) -> None:
        body = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args: Any) -> None:  # noqa: A002 -- the base's name
        del format, args


def _blocks(request: dict[str, Any]) -> list[dict[str, Any]]:
    """The blocks the prompt showed, as the view renders them."""
    return [
        json.loads(line)
        for message in request["messages"]
        for line in str(message.get("content", "")).splitlines()
        if line.startswith('{"t":"block"')
    ]


def _claimed(request: dict[str, Any]) -> list[dict[str, Any]]:
    """One claim per name a shown block's text holds: the name is a party, quoted by its block."""
    return [
        {"subject": name, "subject_etype": "org", "claim_type": "attribute",
         "predicate": "is_party", "object": None, "object_is_entity": False,
         "status": "asserted", "t_start": None, "t_end": None, "description": None,
         "cite": block["cite"], "quote": name}
        for block in _blocks(request)
        for name in NAMES
        if name in str(block.get("text", ""))
    ]  # fmt: skip


def _named(request: dict[str, Any]) -> list[dict[str, Any]]:
    """One entity per name a shown block's text holds, cited to that block and quoting the name."""
    found: list[dict[str, Any]] = []
    for message in request["messages"]:
        for line in str(message.get("content", "")).splitlines():
            if not line.startswith('{"t":"block"'):
                continue
            block = json.loads(line)
            found.extend(
                {"name": name, "etype": None, "cite": block["cite"], "quote": name,
                 "description": None}
                for name in NAMES
                if name in str(block.get("text", ""))
            )  # fmt: skip
    return found


@pytest.fixture
def model() -> Iterator[str]:
    _Model.asked, _Model.delay_s = [], 0.0
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _Model)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}"
    finally:
        server.shutdown()
        server.server_close()


def _project(
    tmp_path: Path, endpoint: str, extra: str = "", billed: tuple[str, ...] = (LLM,)
) -> tuple[Path, Any]:
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "memo.md").write_text(MEMO, encoding="utf-8")
    listed = {
        "enabled": [*SHIPPED_DRIVERS, *billed],
        "classes": ["free", "local_compute", "billed_api"],
        "passes": [*SHIPPED_PASSES, *billed],
    }
    toml = (
        PROJECT
        + OPT_IN
        + f"enabled = {json.dumps(listed['enabled'])}\n"
        + f"[drivers.cost]\nallow_classes = {json.dumps(listed['classes'])}\n"
        + f"[graph.passes]\nenable = {json.dumps(listed['passes'])}\n"
        + f'[services.llm]\nmodel_id = "{MODEL}"\nmodel_revision = "{REV}"\n'
        + f'endpoint = "{endpoint}"\n'
        + extra
    )
    (tmp_path / "omniweave.toml").write_text(toml, encoding="utf-8")
    config = load(cwd=tmp_path, env={"OMNIWEAVE_HOME": str(tmp_path / "owhome")})
    return tmp_path / ".omniweave" / "index.owstore", config


def test_a_billed_pass_runs_per_segment_and_writes_under_its_decision(
    tmp_path: Path, model: str
) -> None:
    store, config = _project(tmp_path, model)
    report = _run(tmp_path, store, config)
    assert report.status == "ok", report.lines()
    segments = _rows(
        store,
        "SELECT count(*) FROM segment AS s JOIN doc AS d ON d.doc_ord = s.doc_ord"
        " AND d.gen = s.gen WHERE s.state = 0 AND s.layer = 0",
    )[0][0]
    line = (
        f"  billed    {LLM}: {segments} Segment(s) of 1 document(s) under the coverage floor, "
        f"{segments} queued"
    )
    assert line in report.lines(), report.lines()
    derived = f"  derive    {LLM}: 1 document(s), {segments} Segment run(s), "
    assert any(one.startswith(derived) for one in report.lines()), "D720: a document, not a row"
    assert _rows(
        store, "SELECT status, count(*) FROM work WHERE operator = 'derive.entity.llm'"
    ) == [("done", segments)]
    runs = _rows(
        store,
        "SELECT r.cost_class, r.status, w.decision_id = r.decision_id FROM derive_run AS r"
        " JOIN work AS w ON w.operator = r.pass_id WHERE r.pass_id = 'derive.entity.llm'"
        " AND w.decision_id = r.decision_id",
    )
    assert len(runs) == segments, runs
    assert {r[0] for r in runs} == {"billed_api"}
    assert {r[1] for r in runs} <= {"ok", "empty"}
    keys = {
        k
        for (k,) in _rows(
            store,
            "SELECT e.key FROM mention AS m JOIN derive_run AS r ON r.run_id = m.run_id"
            " JOIN entity AS e ON e.entity_id = m.entity_id WHERE r.pass_id = 'derive.entity.llm'",
        )
    }
    assert keys == {"acme_holdings", "beta_corp"}, keys
    assert len(_Model.asked) == segments, "one call per Segment, and no glean"
    spends = [
        json.loads(s)
        for (s,) in _rows(store, "SELECT spend FROM derive_run WHERE pass_id = 'derive.entity.llm'")
    ]
    assert len(spends) == segments
    assert all(
        (s["calls"], s["tokens_in"], s["tokens_out"]) == (1, 120, 30) and s["bytes_egress"] > 0
        for s in spends
    ), "D730: each run carries the call its Segment cost, as the provider reported it"
    assert {request["model"] for request in _Model.asked} == {MODEL}


def test_a_second_ingest_bills_nothing_again(tmp_path: Path, model: str) -> None:
    """Ruling 5 of D715: the rows converge, so nothing is queued and the model is not called."""
    store, config = _project(tmp_path, model)
    assert _run(tmp_path, store, config).status == "ok"
    calls = len(_Model.asked)
    again = _run(tmp_path, store, config)
    assert again.status == "ok", again.lines()
    assert any(
        line.startswith(f"  billed    {LLM}: ") and line.endswith(", 0 queued")
        for line in again.lines()
    ), again.lines()
    assert len(_Model.asked) == calls


def test_a_model_that_will_not_attach_fails_the_rows_and_the_run_goes_on(
    tmp_path: Path,
) -> None:
    """D713: an unreachable Service fails the billed rows with its fix; free work still lands."""
    store, config = _project(tmp_path, "http://127.0.0.1:9")
    report = _run(tmp_path, store, config)
    failed = _rows(
        store,
        "SELECT DISTINCT status, failure_class FROM work WHERE operator = 'derive.entity.llm'",
    )
    assert failed == [("failed_permanent", "upstream_unavailable")], report.lines()
    assert _rows(store, "SELECT count(*) FROM work WHERE operator = 'derive.segment'"
                        " AND status = 'done'") == [(1,)]  # fmt: skip


def test_the_run_is_llm_and_each_invoke_names_its_segment(
    tmp_path: Path, model: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`derive_run.method` is `llm` (06:1.7), and a billed unit is its Segment's part, not ''."""
    from omniweave.run.operators import derive  # noqa: PLC0415

    parts: list[str] = []
    invocation = derive._Source.invocation

    def recorded(self: Any, call: Any) -> Any:
        built = invocation(self, call)
        if built.lane == "entity" and built.services:
            parts.extend(unit.part for unit in built.units)
        return built

    monkeypatch.setattr(derive._Source, "invocation", recorded)
    store, config = _project(tmp_path, model)
    assert _run(tmp_path, store, config).status == "ok"
    assert parts and all(part.startswith("seg:") for part in parts), parts
    assert _rows(
        store,
        "SELECT DISTINCT v.name FROM derive_run AS r JOIN enum_val AS v"
        " ON v.domain = 'method' AND v.ord = r.method WHERE r.pass_id = 'derive.entity.llm'",
    ) == [("llm",)]


def test_a_billed_drain_that_crashed_leaves_the_run_partial(
    tmp_path: Path, model: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    from omniweave.run.operators import derive  # noqa: PLC0415

    def crash(_self: object, _row: object, _billed: object) -> object:
        raise RuntimeError("the billed view could not be read")

    monkeypatch.setattr(derive.DeriveOperator, "_billed_view", crash)
    store, config = _project(tmp_path, model)
    report = _run(tmp_path, store, config)
    assert report.status == "partial", report.lines()
    assert _Model.asked == []


def test_a_billed_view_is_its_rows_live_segment_or_nothing(tmp_path: Path, model: str) -> None:
    """D716: the part finds the live Segment; a stale part, a bare row or an unknown unit, none."""
    import sqlite3  # noqa: PLC0415, TID251 -- the view is read off the store the run wrote

    from omniweave.run.operators import derive  # noqa: PLC0415
    from omniweave.run.operators.parse import ParseTally  # noqa: PLC0415
    from omniweave_core.store.coverage import BILLED_PASSES  # noqa: PLC0415

    store, config = _project(tmp_path, model)
    assert _run(tmp_path, store, config).status == "ok"
    connection = sqlite3.connect(store)
    try:
        thread = SimpleNamespace(run=lambda unit: unit.run(connection))
        operator = derive.DeriveOperator(cast("Any", None), cast("Any", thread), ParseTally())
        [(uri, part)] = connection.execute(
            "SELECT unit_uri, unit_part FROM work WHERE operator = 'derive.entity.llm'"
            " ORDER BY unit_part LIMIT 1"
        ).fetchall()
        billed = BILLED_PASSES[0]

        def view(**row: str) -> tuple[Any, ...]:
            fields = {"unit_uri": uri, "unit_part": part, **row}
            return operator._billed_view(cast("Any", SimpleNamespace(**fields)), billed)

        [found] = view()
        assert found.seg == part
        assert b'"etypes"' in found.body, "the billed view, not the free one"
        assert view(unit_part="seg:0000000000000000") == ()
        assert view(unit_part="") == ()
        assert view(unit_part=part.removeprefix("seg:")) == (), "a part is seg: and its digest"
        assert view(unit_uri="file:///nowhere.md") == ()
        connection.execute(
            "UPDATE segment SET state = 1 WHERE substr(lower(hex(content_digest)), 1, 16) = ?",
            (part.removeprefix("seg:"),),
        )
        assert view() == (), "a retired Segment is no row's any more"
        connection.rollback()
    finally:
        connection.close()


def test_the_cards_watchdog_outlasts_one_service_call() -> None:
    """D718: PROGRESS comes between Segments, so `progress_ms` must cover one call at its bound,
    the Service's `request_timeout_s`. `wall_ms_hard` covers the whole INVOKE at that bound."""
    from omniweave_core.discovery import catalog  # noqa: PLC0415
    from omniweave_core.modelserver import ServiceSpec  # noqa: PLC0415

    card = catalog().cards.get(LLM)
    assert card is not None
    spec = card.isolation
    call_ms = ServiceSpec(name="llm", model_id=MODEL, model_revision=REV).request_timeout_s * 1000
    assert spec.progress_ms >= call_ms
    assert spec.wall_ms_hard >= spec.batch_max_units * call_ms
    assert spec.batch_max_units == 4


def test_a_batch_longer_than_its_lease_is_extended_and_lands(tmp_path: Path, model: str) -> None:
    """D719, 08:462-470: the drain's own claims outlive `lease_ms` and are extended, never reaped.

    A 600 ms lease against a model that answers in 1.5 s a call: every billed batch outlives its
    lease, and so does any worker's start-up. A reap would return the rows to `pending` and
    supersede their answers; an extension lets each batch land.
    """
    _Model.delay_s = 1.5
    store, config = _project(
        tmp_path, model, extra="[runtime]\nlease_ms = 600\nlease_extend_ms = 200\n"
    )
    report = _run(tmp_path, store, config)
    assert report.status == "ok", report.lines()
    assert _rows(
        store, "SELECT DISTINCT status FROM work WHERE operator = 'derive.entity.llm'"
    ) == [("done",)]
    assert _rows(store, "SELECT count(*) FROM work WHERE status <> 'done'") == [(0,)]
    keys = {
        k
        for (k,) in _rows(
            store,
            "SELECT e.key FROM mention AS m JOIN derive_run AS r ON r.run_id = m.run_id"
            " JOIN entity AS e ON e.entity_id = m.entity_id"
            " WHERE r.pass_id = 'derive.entity.llm'",
        )
    }
    assert keys == {"acme_holdings", "beta_corp"}


def test_the_claim_pass_runs_beside_the_entity_pass_and_binds_its_subjects(
    tmp_path: Path, model: str
) -> None:
    """D722: `derive.claim.llm` in a real ingest, its claims on the entities the names are."""
    claim_llm = "derive.claim.llm"
    store, config = _project(tmp_path, model, billed=(LLM, claim_llm))
    report = _run(tmp_path, store, config)
    assert report.status == "ok", report.lines()
    assert _rows(store, "SELECT DISTINCT status FROM work WHERE operator = 'derive.claim.llm'") == [
        ("done",)
    ]
    lanes = [request["response_format"]["json_schema"]["name"] for request in _Model.asked]
    #  D724: the entity place drains before the claim place is enqueued, and a claim is offered
    #  only where an entity was found -- not the Notes Segment, which names nobody.
    entity_calls, claim_calls = lanes.count("owgraph_entity"), lanes.count("owgraph_claim")
    assert lanes == ["owgraph_entity"] * entity_calls + ["owgraph_claim"] * claim_calls, lanes
    assert (claim_calls, entity_calls) == (2, 3)
    claims = _rows(
        store,
        "SELECT DISTINCT e.key, c.predicate FROM claim AS c"
        " JOIN entity AS e ON e.entity_id = c.subject_entity"
        " JOIN derive_run AS r ON r.run_id = c.run_id WHERE r.pass_id = 'derive.claim.llm'"
        " ORDER BY e.key",
    )
    assert claims == [("acme_holdings", "is_party"), ("beta_corp", "is_party")]
    assert any(line.startswith(f"  billed    {claim_llm}: ") for line in report.lines())


def test_the_claim_card_is_placed_after_the_entity_card_and_timed_alike() -> None:
    """D722: 06:841's row 12, rank 2 phase 20; its subjects are entity frames; D718's timing."""
    from omniweave_core.discovery import catalog  # noqa: PLC0415
    from omniweave_core.store.coverage import BILLED_PASSES  # noqa: PLC0415

    cards = catalog().cards
    entity_card, claim_card = cards.get(LLM), cards.get("derive.claim.llm")
    assert entity_card is not None and claim_card is not None
    assert claim_card.derive is not None and sorted(claim_card.derive.items) == ["claim", "entity"]
    assert claim_card.cost_model is not None
    assert dict(claim_card.cost_model.per_part) == {
        "tokens_in": 3100,
        "tokens_out": 480,
        "calls": 1,
    }
    assert claim_card.isolation == entity_card.isolation
    assert claim_card.identity.entrypoint == "omniweave_llm.claim_llm.driver:ClaimLLM"
    places = {b.pass_id: b.place for b in BILLED_PASSES}
    assert places["derive.claim.llm"] == (2, 20) > places[LLM]
    assert claim_card.derive_sibling is not None and entity_card.derive_sibling is not None
    assert (claim_card.derive_sibling.phase, entity_card.derive_sibling.phase) == (20, 10)


# ---------------------------------------------------------------------------------------------
# D725: the call cache
# ---------------------------------------------------------------------------------------------

COPY = MEMO + "\n## Extra\n\nBeta Corp signs.\n"
"""A second file whose first three Segments are the memo's, and a fourth that is new."""

_MENTIONS_BY_DOC = (
    "SELECT b.doc_ord, group_concat(DISTINCT e.key), count(*) FROM mention AS m"
    " JOIN block AS b ON b.block_id = m.block_id JOIN segment AS s ON s.segment_id = m.segment_id"
    " JOIN entity AS e ON e.entity_id = m.entity_id JOIN derive_run AS r ON r.run_id = m.run_id"
    " WHERE r.pass_id = 'derive.entity.llm' AND b.doc_ord = s.doc_ord"
    " GROUP BY b.doc_ord ORDER BY b.doc_ord"
)
_KEPT = "SELECT count(*), sum(hits) FROM cache_index WHERE driver = 'derive.entity.llm'"


def _write(store: Path, sql: str) -> None:
    import sqlite3  # noqa: PLC0415, TID251 -- the test edits the cache the run wrote.

    connection = sqlite3.connect(store)
    try:
        connection.execute(sql)
        connection.commit()
    finally:
        connection.close()


def test_a_segment_another_file_holds_is_answered_from_the_call_cache(
    tmp_path: Path, model: str
) -> None:
    """D725, rulings 9 and 11: the copy's first three Segments are the memo's questions, so only
    the new one is bought, and the replayed mentions land on the copy's blocks under its rows."""
    store, config = _project(tmp_path, model)
    assert _run(tmp_path, store, config).status == "ok"
    calls = len(_Model.asked)
    assert _rows(
        store,
        "SELECT count(*), min(layer), min(cost_class), sum(hits) FROM cache_index"
        " WHERE driver = 'derive.entity.llm'",
    ) == [(calls, "call", "billed_api", 0)], "ruling 10: every answer that parsed is kept"
    kept = [
        json.loads(s)
        for (s,) in _rows(
            store, "SELECT spend_json FROM cache_index WHERE driver = 'derive.entity.llm'"
        )
    ]
    assert all((k["calls"], k["tokens_in"], k["tokens_out"]) == (1, 120, 30) for k in kept), kept
    (tmp_path / "docs" / "copy.md").write_text(COPY, encoding="utf-8")
    report = _run(tmp_path, store, config)
    assert report.status == "ok", report.lines()
    assert len(_Model.asked) == calls + 1, "only the Extra Segment is bought"
    assert "Beta Corp signs." in json.dumps(_Model.asked[-1])
    assert any(
        line.startswith(f"  derive    {LLM}: 1 document(s), {calls + 1} Segment run(s), ")
        and line.endswith(f", {calls} from the call cache")
        for line in report.lines()
    ), report.lines()
    memo, copy = _rows(store, _MENTIONS_BY_DOC)
    assert set(memo[1].split(",")) == set(copy[1].split(",")) == {"acme_holdings", "beta_corp"}
    assert (memo[2], copy[2]) == (2, 3), "the copy's two replayed mentions and its new one"
    assert _rows(store, _KEPT) == [(calls + 1, calls)], "a hit adds no entry and counts on its own"
    runs = _rows(
        store,
        "SELECT r.status, r.cost_class, w.status FROM derive_run AS r"
        " JOIN work AS w ON w.decision_id = r.decision_id AND w.operator = r.pass_id"
        " JOIN segment AS s ON s.segment_id = r.segment_id"
        " WHERE r.pass_id = 'derive.entity.llm' AND s.doc_ord = (SELECT max(doc_ord) FROM doc)",
    )
    assert len(runs) == calls + 1, runs
    assert {r[1:] for r in runs} == {("billed_api", "done")}
    assert {r[0] for r in runs} <= {"ok", "empty"}


def test_a_new_generation_of_one_document_rebills_nothing(tmp_path: Path, model: str) -> None:
    """06:2395: a Segment that re-enters on a new generation with its text unchanged is a hit.

    A second file of the same bytes is the same document at a new generation, and its billed rows
    are new rows; the cache answers every one."""
    store, config = _project(tmp_path, model)
    assert _run(tmp_path, store, config).status == "ok"
    calls = len(_Model.asked)
    (tmp_path / "docs" / "again.md").write_text(MEMO, encoding="utf-8")
    report = _run(tmp_path, store, config)
    assert report.status == "ok", report.lines()
    assert len(_Model.asked) == calls
    assert any(line.endswith(f", {calls} from the call cache") for line in report.lines())


def test_an_entry_recorded_for_another_segment_is_not_replayed(tmp_path: Path, model: str) -> None:
    """Billed ruling 12: clause 5 is asked of the Segment's part, so a part that differs is a
    collision and the model is asked."""
    store, config = _project(tmp_path, model)
    assert _run(tmp_path, store, config).status == "ok"
    calls = len(_Model.asked)
    _write(store, "UPDATE cache_index SET unit_part = 'seg:0000000000000000'")
    (tmp_path / "docs" / "copy.md").write_text(COPY, encoding="utf-8")
    report = _run(tmp_path, store, config)
    assert report.status == "ok", report.lines()
    assert len(_Model.asked) == 2 * calls + 1
    assert not any("from the call cache" in line for line in report.lines()), report.lines()


def test_an_entry_whose_blob_is_gone_is_a_miss_and_the_next_answer_heals_it(
    tmp_path: Path, model: str
) -> None:
    """08:1439 clause 2: a corrupt entry is a miss, never a failure, and the next success
    overwrites it."""
    store, config = _project(tmp_path, model)
    assert _run(tmp_path, store, config).status == "ok"
    calls = len(_Model.asked)
    _write(store, "UPDATE cache_index SET ref = 'cas://00/00/' || printf('%064d', 0)")
    (tmp_path / "docs" / "copy.md").write_text(COPY, encoding="utf-8")
    report = _run(tmp_path, store, config)
    assert report.status == "ok", report.lines()
    assert len(_Model.asked) == 2 * calls + 1
    assert _rows(store, "SELECT count(*) FROM cache_index WHERE ref LIKE 'cas://00/00/0000%'") == [
        (0,)
    ]
    (tmp_path / "docs" / "third.md").write_text(
        COPY + "\nAcme Holdings agrees.\n", encoding="utf-8"
    )
    assert _run(tmp_path, store, config).status == "ok"
    assert len(_Model.asked) == 2 * calls + 2, "the healed entries answer the third file"


def test_the_merge_card_is_corpus_grained_billed_and_declares_its_witness_set() -> None:
    """D726: 06:842's row 13, rank 2 phase 30 at `corpus` granularity, per 30-pair batch; 04:2519's
    witness set, which resolve() would otherwise refuse as `NO_WITNESS_SET`; D718's timing."""
    from omniweave_core.discovery import catalog  # noqa: PLC0415
    from omniweave_ports.types import ArtifactKind  # noqa: PLC0415

    cards = catalog().cards
    merge_card, entity_card = cards.get("derive.merge.llm"), cards.get(LLM)
    assert merge_card is not None and entity_card is not None
    assert merge_card.identity.granularity == "corpus"
    assert merge_card.identity.entrypoint == "omniweave_llm.merge_llm.driver:MergeLLM"
    assert set(merge_card.capability.produces) == {
        ArtifactKind.GRAPH_ITEMS,
        ArtifactKind.WITNESS_SET,
    }
    assert merge_card.cost_model is not None
    assert merge_card.cost_model.cost_class == "billed_api"
    assert dict(merge_card.cost_model.per_part) == {
        "tokens_in": 2100,
        "tokens_out": 240,
        "calls": 1,
    }
    assert merge_card.derive_sibling is not None
    assert (merge_card.derive_sibling.phase, merge_card.derive_sibling.prompt_version) == (30, "1")
    assert merge_card.isolation == entity_card.isolation
    assert merge_card.degradations == ()


def test_the_report_card_is_corpus_grained_billed_and_declares_its_witness_set() -> None:
    """D731: 06:843's row 14, rank 2 phase 40 at `corpus` granularity, per community at the
    bounds; 04:2519's witness set; a report is a `summary`; D718's timing."""
    from omniweave_core.discovery import catalog  # noqa: PLC0415
    from omniweave_ports.types import ArtifactKind  # noqa: PLC0415

    cards = catalog().cards
    report_card, entity_card = cards.get("derive.report.llm"), cards.get(LLM)
    assert report_card is not None and entity_card is not None
    assert report_card.identity.granularity == "corpus"
    assert report_card.identity.entrypoint == "omniweave_llm.report_llm.driver:ReportLLM"
    assert set(report_card.capability.produces) == {
        ArtifactKind.GRAPH_ITEMS,
        ArtifactKind.WITNESS_SET,
    }
    assert report_card.derive is not None and sorted(report_card.derive.items) == ["summary"]
    assert report_card.cost_model is not None
    assert report_card.cost_model.cost_class == "billed_api"
    assert dict(report_card.cost_model.per_part) == {
        "tokens_in": 8000,
        "tokens_out": 2000,
        "calls": 1,
    }
    assert report_card.derive_sibling is not None
    assert (report_card.derive_sibling.phase, report_card.derive_sibling.prompt_version) == (
        40,
        "1",
    )
    assert report_card.isolation == entity_card.isolation
    assert report_card.degradations == ()
