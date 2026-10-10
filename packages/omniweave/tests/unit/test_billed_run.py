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
    "## Payment\n\nBeta Corp pays on delivery.\n"
)
NAMES = ("Acme Holdings", "Beta Corp")


class _Model(http.server.BaseHTTPRequestHandler):
    """A model server: `/health`, `/v1/models`, and an answer naming what the blocks name."""

    asked: ClassVar[list[dict[str, Any]]] = []

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
        answer = {"entities": _named(request), "relations": [], "more_available": False}
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
    _Model.asked = []
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _Model)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}"
    finally:
        server.shutdown()
        server.server_close()


def _project(tmp_path: Path, endpoint: str) -> tuple[Path, Any]:
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "memo.md").write_text(MEMO, encoding="utf-8")
    listed = {
        "enabled": [*SHIPPED_DRIVERS, LLM],
        "classes": ["free", "local_compute", "billed_api"],
        "passes": [*SHIPPED_PASSES, LLM],
    }
    toml = (
        PROJECT
        + OPT_IN
        + f"enabled = {json.dumps(listed['enabled'])}\n"
        + f"[drivers.cost]\nallow_classes = {json.dumps(listed['classes'])}\n"
        + f"[graph.passes]\nenable = {json.dumps(listed['passes'])}\n"
        + f'[services.llm]\nmodel_id = "{MODEL}"\nmodel_revision = "{REV}"\n'
        + f'endpoint = "{endpoint}"\n'
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
