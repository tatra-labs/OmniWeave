"""`omniweave_serve.launch`: the entry point `ow serve` loads, and the contract across the boundary.

The boundary is the point. `omniweave` and this distribution may not import each other, so the
three facts that make the handoff work are each written twice, once on each side, and bound here
by a test that imports both (G4 scans source, not tests):

1. the group and the name: `pyproject.toml`'s `[project.entry-points."omniweave.serve"] mcp`
   against `omniweave.surface.dispatch.SERVE_GROUP` / `SERVE_NAME`;
2. the value: `launch:run`, the function actually loaded;
3. the signature: `run`'s keyword-only builtins against `dispatch.ServeEntry`.

Coroutines are stepped with `send(None)`, as in `test_serve_dispatch.py`, so no loop is started.
"""

from __future__ import annotations

import ast
import inspect
import io
import tomllib
from collections.abc import Coroutine
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, TypeVar

import omniweave_serve.launch as launch_module
import pytest
from omniweave.surface import dispatch as cli_side
from omniweave_core.errors import ConfigError, InternalError
from omniweave_serve.dispatch import McpDispatcher, Surface
from omniweave_serve.launch import OK, report, run, run_on
from omniweave_serve.stdio import JSONRPC, Line, encode

T = TypeVar("T")
DIST_ROOT = Path(__file__).resolve().parents[2]


def _drive(coroutine: Coroutine[Any, Any, T]) -> T:
    try:
        coroutine.send(None)
    except StopIteration as done:
        return done.value
    coroutine.close()
    pytest.fail("the coroutine suspended; nothing on this path may wait")


@dataclass
class Scripted:
    lines: list[Line]

    async def readline(self) -> Line:
        return self.lines.pop(0) if self.lines else Line(b"")


@dataclass
class Sink:
    fail: bool = False
    frames: list[bytes] = field(default_factory=list)

    async def send(self, frame: bytes) -> None:
        if self.fail:
            raise BrokenPipeError
        self.frames.append(frame)


def _ping() -> Line:
    return Line(encode({"jsonrpc": JSONRPC, "id": 1, "method": "ping"}))


def _dispatcher() -> McpDispatcher:
    return McpDispatcher.create(Surface(profile="default", compact=True, corpus_resolves=True))


def test_the_host_closing_its_end_is_a_clean_exit() -> None:
    sink = Sink()
    assert _drive(run_on(Scripted([_ping()]), sink, _dispatcher())) == OK == 0
    assert len(sink.frames) == 1


def test_a_write_that_fails_mid_answer_is_not_a_clean_exit() -> None:
    """`Served.stopped_by`'s own docstring: the caller turns `PEER_GONE` into a non-zero exit."""
    code = _drive(run_on(Scripted([_ping()]), Sink(fail=True), _dispatcher()))
    assert code == InternalError.EXIT


def test_the_startup_report_names_the_unpublished_tools_and_nothing_else() -> None:
    """D507, said once, on stderr, where the host's server log keeps it."""
    assert report(Surface("default", compact=True, corpus_resolves=True)) == ()
    (line,) = report(Surface("full", compact=True, corpus_resolves=True))
    for name in ("ow_coverage", "ow_diff", "ow_doctor", "ow_explain", "ow_grid"):
        assert name in line
    assert line.isascii()


def test_a_bad_profile_raises_before_stdio_is_bound(monkeypatch: pytest.MonkeyPatch) -> None:
    """02:723's *"before the transport opens"*: `create()` runs before `pipes()`."""

    def bound() -> None:
        raise AssertionError("pipes() was called before the dispatcher was built")

    monkeypatch.setattr(launch_module, "pipes", bound)
    with pytest.raises(ConfigError, match="is not a profile"):
        run(
            profile="everything",
            compact=True,
            corpus_resolves=True,
            corpus=None,
            corpora={},
            sessions=None,
            stderr=io.StringIO(),
        )


# ---------------------------------------------------------------------------------------------
# the contract across the boundary
# ---------------------------------------------------------------------------------------------


def test_the_declared_entry_point_is_the_one_the_cli_looks_up() -> None:
    project = tomllib.loads((DIST_ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]
    group = project["entry-points"][cli_side.SERVE_GROUP]
    assert group == {cli_side.SERVE_NAME: "omniweave_serve.launch:run"}
    assert project["name"] == cli_side.SERVE_DISTRIBUTION


def test_runs_signature_is_the_protocol_the_cli_calls() -> None:
    """Keyword-only, builtin types, an `int` back: a type from either side is one the other
    cannot import. `stderr` is this side's own seam and has a default, so the CLI never sees it."""
    ours = inspect.signature(run)
    theirs = inspect.signature(cli_side.ServeEntry.__call__)
    wanted = [name for name in theirs.parameters if name != "self"]
    assert [
        name for name, one in ours.parameters.items() if one.default is inspect.Parameter.empty
    ] == wanted
    assert all(one.kind is inspect.Parameter.KEYWORD_ONLY for one in ours.parameters.values())
    for name in wanted:
        assert ours.parameters[name].annotation == theirs.parameters[name].annotation
    assert ours.return_annotation == theirs.return_annotation == "int"


def test_asyncio_is_named_once_for_run() -> None:
    """The exemption's scope, asserted over the AST: one attribute of `asyncio`, `run`."""
    tree = ast.parse(Path(launch_module.__file__).read_text(encoding="utf-8"))
    used = [
        node.attr
        for node in ast.walk(tree)
        if isinstance(node, ast.Attribute)
        and isinstance(node.value, ast.Name)
        and node.value.id == "asyncio"
    ]
    assert used == ["run"]
