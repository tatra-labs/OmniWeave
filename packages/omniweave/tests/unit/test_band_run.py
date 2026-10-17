"""The LLM band in a real ingest: `derive.merge.llm` against a loopback model. **D729.**

Two documents whose Northwind spellings score 88.24 across them, the one pair `op.resolve` cannot
decide (D727). The band's row (D728) runs as one INVOKE a batch through the worker's Service grant
(D712, D713), the model answers by position (D726), and a `same` answer is an `llm_band` merge
`op.resolve` reads back into the closure in the same run.
"""

from __future__ import annotations

import http.server
import json
import sqlite3  # noqa: TID251 -- the assertions read and edit the store a run wrote.
import threading
from typing import TYPE_CHECKING, Any, ClassVar

import pytest
from omniweave_core.config import SHIPPED_DRIVERS, SHIPPED_PASSES, load
from omniweave_core.model.enums import Trust
from test_graph_resolve import NORTH_A, NORTH_B
from test_run_parse import OPT_IN, PROJECT, _rows, _run

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

MERGE = "derive.merge.llm"
MODEL = "qwen3:4b"
REV = "0123456789abcdef0123456789abcdef01234567"


class _Judge(http.server.BaseHTTPRequestHandler):
    """A model server that decides every pair it is shown, the same way."""

    asked: ClassVar[list[dict[str, Any]]] = []
    same: ClassVar[bool] = True
    stray: ClassVar[bool] = False

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
        pairs = _pairs(request)
        decisions = [
            {"pair": p["pair"], "same": type(self).same, "reason": "one trading company"}
            for p in pairs
        ]
        if type(self).stray:
            decisions = [{"pair": len(pairs) + 4, "same": True, "reason": "a pair never sent"}]
        self._reply(
            200,
            {
                "choices": [
                    {
                        "message": {
                            "role": "assistant",
                            "content": json.dumps({"decisions": decisions}),
                        }
                    }
                ],
                "usage": {"prompt_tokens": 400, "completion_tokens": 40},
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


def _pairs(request: dict[str, Any]) -> list[dict[str, Any]]:
    """The pair frames the prompt showed."""
    return [
        json.loads(line)
        for message in request["messages"]
        for line in str(message.get("content", "")).splitlines()
        if line.startswith('{"t":"pair"')
    ]


@pytest.fixture
def judge() -> Iterator[str]:
    _Judge.asked, _Judge.same, _Judge.stray = [], True, False
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _Judge)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}"
    finally:
        server.shutdown()
        server.server_close()


def _project(tmp_path: Path, endpoint: str) -> tuple[Path, Any]:
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "a.csv").write_text(NORTH_A, encoding="utf-8")
    (tmp_path / "docs" / "b.csv").write_text(NORTH_B, encoding="utf-8")
    toml = (
        PROJECT
        + OPT_IN
        + f"enabled = {json.dumps([*SHIPPED_DRIVERS, MERGE])}\n"
        + '[drivers.cost]\nallow_classes = ["free", "local_compute", "billed_api"]\n'
        + f"[graph.passes]\nenable = {json.dumps([*SHIPPED_PASSES, MERGE])}\n"
        + f'[services.llm]\nmodel_id = "{MODEL}"\nmodel_revision = "{REV}"\n'
        + f'endpoint = "{endpoint}"\n'
    )
    (tmp_path / "omniweave.toml").write_text(toml, encoding="utf-8")
    config = load(cwd=tmp_path, env={"OMNIWEAVE_HOME": str(tmp_path / "owhome")})
    return tmp_path / ".omniweave" / "index.owstore", config


MERGES = (
    "SELECT l.key, w.key, m.stage, m.trust, m.score, m.score_kind, m.reason, r.pass_id,"
    " r.cost_class, r.decision_id, m.retired_at_gen FROM entity_merge AS m"
    " JOIN entity AS l ON l.entity_id = m.loser_id JOIN entity AS w ON w.entity_id = m.winner_id"
    " JOIN derive_run AS r ON r.run_id = m.run_id WHERE m.stage = 'llm_band'"
)
HEADS = (
    "SELECT DISTINCT canonical_id, resolution_trust FROM entity"
    " WHERE key IN ('northwind_traders', 'northwind_trading')"
)


def test_the_band_is_asked_once_and_its_merge_joins_the_closure(tmp_path: Path, judge: str) -> None:
    store, config = _project(tmp_path, judge)
    report = _run(tmp_path, store, config)
    assert report.status == "ok", report.lines()
    [request] = _Judge.asked
    assert request["response_format"]["json_schema"]["name"] == "owgraph_merge"
    [pair] = _pairs(request)
    assert (pair["a"]["surface"], pair["b"]["surface"]) == (
        "Northwind Traders",
        "Northwind Trading",
    )
    assert "northwind_traders" not in json.dumps(request), "GR11: no key reaches the model"
    [(loser, winner, _stage, trust, score, kind, reason, pass_id, cost, decision, retired)] = _rows(
        store, MERGES
    )
    assert (loser, winner) == ("northwind_trading", "northwind_traders")
    assert (trust, kind, reason, pass_id, cost, retired) == (
        int(Trust.INFERRED), "jaro_winkler", "one trading company", MERGE, "billed_api", None,
    )  # fmt: skip
    assert score == pytest.approx(88.24, abs=0.01)
    assert _rows(
        store,
        f"SELECT status, decision_id FROM work WHERE operator = '{MERGE}'",  # noqa: S608
    ) == [("done", decision)]
    [(head, resolution)] = _rows(store, HEADS)
    assert resolution == int(Trust.INFERRED)
    lines = report.lines()
    assert f"  band      {MERGE}: 1 pair(s) in 1 batch(es), 1 queued" in lines, lines
    assert any("1 by the LLM band" in line for line in lines), lines
    assert any(", 1 in the LLM band, " in line for line in lines), "D730: built, so not unbuilt"
    assert any(line.startswith(f"  band      {MERGE}: 1 row(s), 1 call(s)") for line in lines), (
        lines
    )
    assert report.resolved is not None and report.resolved.band == ()
    [(spend,)] = _rows(store, f"SELECT spend FROM derive_run WHERE pass_id = '{MERGE}'")  # noqa: S608
    run = json.loads(spend)
    assert (run["calls"], run["tokens_in"], run["tokens_out"]) == (1, 400, 40), run
    assert run["bytes_egress"] > 0
    [(share,)] = _rows(store, f"SELECT spend_json FROM cache_index WHERE driver = '{MERGE}'")  # noqa: S608
    assert json.loads(share)["tokens_in"] == 400, "one pair: the whole batch's Spend"
    assert _rows(
        store,
        "SELECT r.attempt, r.tokens_in, r.tokens_out, r.calls, r.was_cache_hit, r.outcome"
        " FROM route_spend AS r JOIN work AS w ON w.decision_id = r.decision_id"
        " WHERE w.operator = 'derive.merge.llm'",
    ) == [(1, 400, 40, 1, 0, "ok")], "D733: the band's one bill"
    assert (
        head == _rows(store, "SELECT entity_id FROM entity WHERE key = 'northwind_traders'")[0][0]
    )


def test_a_second_ingest_asks_nothing_and_keeps_the_merge(tmp_path: Path, judge: str) -> None:
    store, config = _project(tmp_path, judge)
    assert _run(tmp_path, store, config).status == "ok"
    again = _run(tmp_path, store, config)
    assert again.status == "ok", again.lines()
    assert len(_Judge.asked) == 1
    assert [r[-1] for r in _rows(store, MERGES)] == [None]
    assert _rows(store, f"SELECT count(*) FROM work WHERE operator = '{MERGE}'") == [(1,)]  # noqa: S608


def test_a_row_the_cache_answers_whole_calls_nothing(tmp_path: Path, judge: str) -> None:
    """Ruling 14: the band asked again under a new row is answered from the call cache."""
    store, config = _project(tmp_path, judge)
    assert _run(tmp_path, store, config).status == "ok"
    connection = sqlite3.connect(store)
    try:
        connection.execute(f"DELETE FROM work WHERE operator = '{MERGE}'")  # noqa: S608
        connection.execute("UPDATE entity_merge SET retired_at_gen = 1 WHERE stage = 'llm_band'")
        connection.commit()
    finally:
        connection.close()
    again = _run(tmp_path, store, config)
    assert again.status == "ok", again.lines()
    assert len(_Judge.asked) == 1, "no second call"
    assert _rows(store, "SELECT sum(hits) FROM cache_index WHERE driver = 'derive.merge.llm'") == [
        (1,)
    ]
    assert [r[-1] for r in _rows(store, MERGES)].count(None) == 1, "landed again from the cache"
    assert _rows(store, f"SELECT status FROM work WHERE operator = '{MERGE}'") == [("done",)]  # noqa: S608
    assert _rows(
        store,
        "SELECT DISTINCT r.attempt, r.tokens_in, r.tokens_out, r.calls, r.was_cache_hit,"
        " r.outcome FROM route_spend AS r JOIN work AS w ON w.decision_id = r.decision_id"
        " WHERE w.operator = 'derive.merge.llm' ORDER BY r.attempt",
    ) == [(1, 400, 40, 1, 0, "ok"), (2, 400, 40, 1, 1, "skipped_cached")], (
        "D733: the same decision's second attempt, a hit replaying the pair's Spend"
    )


def test_a_pair_the_model_keeps_apart_is_not_merged_nor_asked_again(
    tmp_path: Path, judge: str
) -> None:
    """Ruling 12-13: `not same` writes nothing, and is kept so it is not bought twice."""
    _Judge.same = False
    store, config = _project(tmp_path, judge)
    report = _run(tmp_path, store, config)
    assert report.status == "ok", report.lines()
    assert _rows(store, MERGES) == []
    assert len(_rows(store, HEADS)) == 2
    connection = sqlite3.connect(store)
    try:
        connection.execute(f"DELETE FROM work WHERE operator = '{MERGE}'")  # noqa: S608
        connection.commit()
    finally:
        connection.close()
    assert _run(tmp_path, store, config).status == "ok"
    assert len(_Judge.asked) == 1


def test_a_decision_for_a_pair_never_sent_is_held(tmp_path: Path, judge: str) -> None:
    """Ruling 11 (D726 ruling 4): quarantined as unparsed, the batch named, and nothing merged."""
    _Judge.stray = True
    store, config = _project(tmp_path, judge)
    assert _run(tmp_path, store, config).status == "ok"
    assert _rows(store, MERGES) == []
    [(code, kind, payload)] = _rows(
        store,
        "SELECT q.code, q.row_kind, q.payload FROM quarantine AS q"
        " JOIN derive_run AS r ON r.run_id = q.run_id WHERE r.pass_id = 'derive.merge.llm'",
    )
    assert (code, kind) == ("OW_GRAPH_UNPARSED_ITEM", "merge")
    held = json.loads(payload)
    assert held["batch"].startswith("band:") and "same" not in held["frame"]


# ---------------------------------------------------------------------------------------------
# the pieces the one-pair runs above cannot tell apart
# ---------------------------------------------------------------------------------------------

SIDES = (
    ({"surface": "Northwind Traders", "etype": "org", "aliases": []},
     {"surface": "Northwind Trading", "etype": "org", "aliases": ["NWT"]}),
    ({"surface": "Contoso Bank", "etype": "org", "aliases": []},
     {"surface": "Contoso Banking", "etype": "org", "aliases": []}),
    ({"surface": "Litware Group", "etype": "org", "aliases": []},
     {"surface": "Litware Grp", "etype": "org", "aliases": []}),
)  # fmt: skip


def _card(prompt: str = "1") -> Any:
    from types import SimpleNamespace  # noqa: PLC0415

    return SimpleNamespace(
        identity=SimpleNamespace(id=MERGE, schema_version=1),
        derive_sibling=SimpleNamespace(prompt_version=prompt),
    )


def test_a_pairs_key_is_its_two_sides_and_what_answers_them() -> None:
    """Ruling 9: the sides, the prompt version and the model move it; a batch or a file does not
    enter it."""
    from omniweave.run.operators.band import pair_key  # noqa: PLC0415

    a, b = SIDES[0]
    key = pair_key(_card(), a, b, MODEL, REV)
    assert key == pair_key(_card(), dict(a), dict(b), MODEL, REV)
    moved = [
        pair_key(_card(), *SIDES[1], MODEL, REV),
        pair_key(_card(), b, a, MODEL, REV),
        pair_key(_card("2"), a, b, MODEL, REV),
        pair_key(_card(), a, b, "qwen3:8b", REV),
        pair_key(_card(), a, b, MODEL, "f" * 40),
    ]
    assert len({key, *moved}) == 6


def test_a_batch_view_renumbers_its_pairs_and_names_no_end() -> None:
    """Ruling 10: the driver's reader (D726) takes it, its positions are 0..n-1, and no entity id
    reaches it."""
    from omniweave.run.operators.band import Manifest, view  # noqa: PLC0415
    from omniweave_llm.merge import read_pairs  # noqa: PLC0415

    one = Manifest(
        members=((101, 102, 88.0), (201, 202, 80.0), (301, 302, 77.0)),
        sides=SIDES,
        witness=(("file:///d/a.csv", "", "northwind_traders"),),
    )
    body = view(one, "band:0123456789abcdef/0", [2, 0])
    read = read_pairs(body)
    assert (read.batch, read.n) == ("band:0123456789abcdef/0", 2)
    assert read.witness == (
        {"unit_uri": "file:///d/a.csv", "unit_part": "", "token": "northwind_traders"},
    )
    pairs = [json.loads(line) for line in read.body.splitlines()]
    assert [p["pair"] for p in pairs] == [0, 1]
    assert [p["a"]["surface"] for p in pairs] == ["Litware Group", "Northwind Traders"]
    assert all(str(n) not in body.decode() for n in (101, 102, 201, 301, 302))


def test_a_decision_is_kept_by_its_position_in_the_batch_sent() -> None:
    """Ruling 11: a frame with no `same`, or a position the batch does not hold, is held."""
    from omniweave.run.operators.band import decided  # noqa: PLC0415

    frames = [
        {"t": "batch", "batch": "band:x/0"},
        {"t": "decision", "pair": 0, "same": True, "reason": "one firm"},
        {"t": "decision", "pair": 1, "unparsed": "{}", "problems": ["pair 1 was answered 2 times"]},
        {"t": "decision", "pair": 2, "same": False, "reason": "outside"},
    ]
    body = b"".join(json.dumps(f).encode() + b"\n" for f in frames)
    found, held = decided(body, 2)
    assert found == {0: (True, "one firm")}
    assert [f["pair"] for f in held] == [1, 2]


def test_the_bands_merges_are_not_billed_items_the_clamp_should_have_seen(
    tmp_path: Path, judge: str
) -> None:
    """D735: the band's run is `billed_api`, but its merges never pass the sink, so neither the
    trust clamp nor grounding applies to them. Counting them as billed items made a band-only store
    read "0.00 clamped: the clamp is not running", the doctor's one failing check."""
    from omniweave.graph.doctor import doctor  # noqa: PLC0415

    store, config = _project(tmp_path, judge)
    assert _run(tmp_path, store, config).status == "ok"
    assert len(_rows(store, MERGES)) == 1
    connection = sqlite3.connect(store)
    try:
        report = doctor(connection, checks=["dangling_tmp", "trust_clamped", "ungrounded"])
    finally:
        connection.close()
    assert report.failed == (), report.failed
    by_check = {f.check: f.detail for f in report.ok}
    assert by_check["trust_clamped"] == "no billed pass has run", by_check
