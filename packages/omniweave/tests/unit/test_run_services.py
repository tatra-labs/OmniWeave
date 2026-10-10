"""A card's Services, granted on derive's `INVOKE` through the run's registry. **D713.**

The registry is built from `[services.*]` when the run's context is, and attaches nothing until a
call names a Service. Derive asks it for every Service the card's `[hardware] services` names, and
sends each handle across as a grant (D712). A Service that will not attach fails the batch's rows
with the attach's own refusal and fix, and the drain goes on.
"""

from __future__ import annotations

import http.server
import io
import json
import threading
from pathlib import Path
from types import SimpleNamespace
from typing import Any, ClassVar, cast

import pytest
from omniweave.run import ingest as ingest_module
from omniweave.run.operators import derive
from omniweave.run.operators.parse import ParseTally
from omniweave_core.clock import SystemClock
from omniweave_core.config import Config, load
from omniweave_core.errors import ConfigError
from omniweave_core.host.subproc import ServiceGrant
from omniweave_core.modelserver import Handle, ServiceRegistry
from omniweave_core.operator import Roots, RunContext
from omniweave_ports.types import UnitRef
from test_run_parse import _project, _rows, _run

MODEL = "qwen3:4b"
REV = "0123456789abcdef0123456789abcdef01234567"
LLM = "derive.entity.llm"


class _Registry:
    """A registry that answers from a script and records which names it was asked for."""

    def __init__(self, handles: dict[str, Any] | None = None, error: Exception | None = None):
        self._handles = handles or {}
        self._error = error
        self.asked: list[str] = []

    def get(self, name: str) -> Any:
        self.asked.append(name)
        if self._error is not None:
            raise self._error
        return self._handles[name]


def _card(*services: str) -> Any:
    return SimpleNamespace(
        hardware=SimpleNamespace(services=services), identity=SimpleNamespace(id=LLM)
    )


def _context(tmp_path: Path, config: Config) -> RunContext:
    roots = Roots(source=tmp_path, output=tmp_path / "out", cache=tmp_path / "cache")
    return ingest_module._context(
        "r_test", 1, config=config, roots=roots, clock=SystemClock(),
        services_root=tmp_path / "services",
    )  # fmt: skip


def _operator(ctx: Any) -> derive.DeriveOperator:
    return derive.DeriveOperator(
        cast("Any", SimpleNamespace(_ctx=ctx)), cast("Any", None), ParseTally()
    )


def _with(services: object) -> derive.DeriveOperator:
    ctx = SimpleNamespace(services=services)
    return _operator(ctx)


def _handle(**overrides: object) -> Handle:
    fields: dict[str, Any] = {
        "name": "llm", "base_url": "http://127.0.0.1:11434", "token": "", "model_id": MODEL,
        "model_rev": REV, "capacity": 1, "traceparent": "", "deadline_ms": 0, "_timeout_s": 30.0,
    }  # fmt: skip
    fields.update(overrides)
    return Handle(**fields)


def test_a_card_that_names_no_service_is_granted_nothing_and_attaches_nothing() -> None:
    registry = _Registry()
    assert _with(registry)._grants(_card()) == ((), "")
    assert registry.asked == []


def test_each_named_service_is_attached_by_its_table_and_granted() -> None:
    registry = _Registry({"llm": _handle()})
    grants, refused = _with(registry)._grants(_card("model:llm"))
    assert (refused, registry.asked) == ("", ["llm"])
    assert grants == (
        ServiceGrant(
            name="llm", base_url="http://127.0.0.1:11434", token="", model_id=MODEL,
            model_rev=REV, request_timeout_s=30,
        ),
    )  # fmt: skip


def test_a_service_that_will_not_attach_is_a_refusal_carrying_its_fix() -> None:
    error = ConfigError("SERVICE_UNREACHABLE: [services.llm]", fix="start the server")
    grants, refused = _with(_Registry(error=error))._grants(_card("model:llm"))
    assert grants == ()
    assert refused.startswith("SERVICE_UNREACHABLE: [services.llm]")
    assert refused.endswith("(fix: start the server)")


def test_a_run_with_no_registry_refuses_and_says_so() -> None:
    grants, refused = _with(None)._grants(_card("model:llm"))
    assert grants == ()
    assert refused == (
        "derive.entity.llm reaches the Services ['model:llm'], and this run carries no "
        "ServiceRegistry to attach them"
    )


def test_the_grants_ride_the_invoke_derive_sends() -> None:
    grant = ServiceGrant(name="llm", base_url="http://127.0.0.1:1", token="", model_id="m",
                         model_rev="r")  # fmt: skip
    source = derive._Source(cast("Any", None), None, (), "entity", (grant,))
    unit = UnitRef(uri="u", part="", content_sha256="0" * 64, byte_len=1)
    call = SimpleNamespace(
        batch=SimpleNamespace(invoke_id="i1"), units=(unit,), deadline_ms=1, budget_micros=0
    )
    assert source.invocation(cast("Any", call)).services == (grant,)
    bare = derive._Source(cast("Any", None), None, (), "anchor")
    assert "services" not in bare.invocation(cast("Any", call)).as_header()


def test_the_runs_context_carries_a_registry_over_every_services_table(tmp_path: Path) -> None:
    """Built from config, and nothing attached by building it (08:1179)."""
    (tmp_path / "omniweave.toml").write_text(
        f'[services.llm]\nmodel_id = "{MODEL}"\nmodel_revision = "{REV}"\n', encoding="utf-8"
    )
    config = load(cwd=tmp_path, env={"OMNIWEAVE_HOME": str(tmp_path / "owhome")})
    registry = _context(tmp_path, config).services
    assert isinstance(registry, ServiceRegistry)
    assert list(registry.live()) == []
    assert (list(registry._specs), registry._root) == (["llm"], tmp_path / "services")
    with pytest.raises(ConfigError, match=r"no \[services\.vlm\] table"):
        registry.get("vlm")


@pytest.mark.parametrize("given", [False, True], ids=["beside-the-cache", "given"])
def test_ingest_hands_its_services_root_to_the_runs_context(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, given: bool
) -> None:
    """A caller with no home keeps the sentinels beside its cache."""
    seen: list[Path] = []
    built = ingest_module._context

    def context(*args: Any, **kwargs: Any) -> RunContext:
        seen.append(kwargs["services_root"])
        return built(*args, **kwargs)

    monkeypatch.setattr(ingest_module, "_context", context)
    store, config = _project(tmp_path, ())
    (tmp_path / "docs" / "memo.md").write_text("# Memo\n", encoding="utf-8")
    root = tmp_path / "owhome" / "services"
    ingest_module.ingest(
        store, config=config, source_root=tmp_path, output_root=tmp_path / "out",
        cache_root=tmp_path / "cache", argv=["ow", "ingest"], paths=[tmp_path / "docs"],
        sweep_ms=20, services_root=root if given else None,
    )  # fmt: skip
    assert seen == [root if given else tmp_path / "cache" / "services"]


def test_the_grants_reach_the_worker_on_every_derive_invoke(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """From `_grants` through `_call` to `_Source`: every derive `INVOKE` carries them."""
    grant = ServiceGrant(name="llm", base_url="http://127.0.0.1:1", token="", model_id="m",
                         model_rev="r")  # fmt: skip
    sent: list[tuple[ServiceGrant, ...]] = []
    invocation = derive._Source.invocation

    def recorded(self: Any, call: Any) -> Any:
        built = invocation(self, call)
        sent.append(built.services)
        return built

    monkeypatch.setattr(derive.DeriveOperator, "_grants", lambda _s, _c: ((grant,), ""))
    monkeypatch.setattr(derive._Source, "invocation", recorded)
    store, config = _project(tmp_path, ())
    (tmp_path / "docs" / "memo.md").write_text("# Memo\n\nSee clause 4.\n", encoding="utf-8")
    assert _run(tmp_path, store, config).status == "ok"
    assert sent and set(sent) == {(grant,)}


class _Server(http.server.BaseHTTPRequestHandler):
    """A model server's two probe paths, reporting `reported` as the model it runs."""

    reported: ClassVar[str] = MODEL

    def do_GET(self) -> None:
        if self.path == "/health":
            payload = b"{}"
        elif self.path == "/v1/models":
            payload = json.dumps({"data": [{"id": type(self).reported}]}).encode()
        else:
            self.send_error(404)
            return
        self.send_response(200)
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, format: str, *args: Any) -> None:  # noqa: A002 -- the base's name
        del format, args


@pytest.mark.parametrize("reported", [MODEL, "llama3:8b"], ids=["verified", "another-model"])
def test_a_pinned_service_is_attached_verified_and_granted(tmp_path: Path, reported: str) -> None:
    """The real registry over a loopback server: the model it reports is checked before a grant."""
    _Server.reported = reported
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _Server)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    endpoint = f"http://127.0.0.1:{server.server_address[1]}"
    try:
        (tmp_path / "omniweave.toml").write_text(
            f'[services.llm]\nmodel_id = "{MODEL}"\nmodel_revision = "{REV}"\n'
            f'endpoint = "{endpoint}"\n',
            encoding="utf-8",
        )
        config = load(cwd=tmp_path, env={"OMNIWEAVE_HOME": str(tmp_path / "owhome")})
        grants, refused = _operator(_context(tmp_path, config))._grants(_card("model:llm"))
    finally:
        server.shutdown()
        server.server_close()
    if reported == MODEL:
        assert refused == ""
        assert [(g.name, g.base_url, g.model_id, g.model_rev) for g in grants] == [
            ("llm", endpoint, MODEL, REV)
        ]
    else:
        assert grants == ()
        assert "llama3:8b" in refused and "(fix: " in refused


def test_a_refused_service_fails_the_passes_rows_and_the_drain_goes_on(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The refusal is each row's failure, permanent and `upstream_unavailable`, with its fix."""

    def refuse(_self: object, _card: object) -> tuple[tuple[ServiceGrant, ...], str]:
        return (), "SERVICE_UNREACHABLE: [services.llm] (fix: start the server)"

    monkeypatch.setattr(derive.DeriveOperator, "_grants", refuse)
    store, config = _project(tmp_path, ())
    (tmp_path / "docs" / "memo.md").write_text("# Memo\n\nSee clause 4.\n", encoding="utf-8")
    report = _run(tmp_path, store, config)
    passes = "SELECT DISTINCT status, failure_class, failure_message FROM work"
    assert _rows(store, passes + " WHERE operator = 'derive.segment'") == [("done", None, None)]
    failed = _rows(
        store, passes + " WHERE operator <> 'derive.segment' AND operator LIKE 'derive.%'"
    )
    assert failed == [
        (
            "failed_permanent",
            "upstream_unavailable",
            "SERVICE_UNREACHABLE: [services.llm] (fix: start the server)",
        )
    ], report.lines()


@pytest.mark.parametrize("verb", ["ingest", "add"])
def test_ow_ingest_and_ow_add_read_sentinels_under_the_home(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, verb: str
) -> None:
    """`$OMNIWEAVE_HOME/services` (08:1060), the root a spawned server's sentinel is written to."""
    from omniweave.surface import add as add_surface  # noqa: PLC0415
    from omniweave.surface import ingest as ingest_surface  # noqa: PLC0415

    seen: dict[str, Any] = {}

    def drained(_store: Path, **kwargs: Any) -> Any:
        seen.update(kwargs)
        return SimpleNamespace(lines=tuple)

    monkeypatch.setattr(ingest_module, "ingest", drained)
    _project(tmp_path, ())
    (tmp_path / "docs" / "memo.md").write_text("# Memo\n", encoding="utf-8")
    main = ingest_surface.main if verb == "ingest" else add_surface.main
    argv = [] if verb == "ingest" else ["add", "docs/memo.md"]
    code = main(
        argv, env={"OMNIWEAVE_HOME": str(tmp_path / "owhome")}, cwd=tmp_path,
        stdout=io.StringIO(), stderr=io.StringIO(),
    )  # fmt: skip
    assert code == 0
    assert seen["services_root"] == tmp_path / "owhome" / "services"
