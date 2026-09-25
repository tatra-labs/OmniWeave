"""`ow serve --mcp`: the launcher, run in-process against an entry point this file hands in.

Every configuration here is a real `omniweave.toml` in `tmp_path`, resolved by the real loader with
an `env` built by the test, so what the entry point receives is what step 5 decided and not what a
test chose. The entry point is a recorder: it never binds stdio, which is `omniweave_serve`'s
half and is measured there and at T3.

**The sharpest test is the order one**,
`test_a_missing_server_is_named_before_a_broken_configuration`: 10:286 makes an absent
distribution a dispatch fact, dispatch is step 1, and a user without `omniweave-serve` must hear
the install command first.
"""

from __future__ import annotations

import ast
import io
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

import pytest
from omniweave.surface import dispatch
from omniweave.surface.dispatch import SERVE_DISTRIBUTION, SERVE_GROUP, SERVE_NAME, serve_entry
from omniweave.surface.serve import HTTP_ONLY, main
from omniweave_core.errors import CapabilityMissing, ConfigError, InternalError, UsageError

if TYPE_CHECKING:
    from collections.abc import Mapping

HANDBOOK = '[corpora.handbook]\npath = ".omniweave/index.owstore"\n'


@dataclass
class Recorder:
    """A `ServeEntry` that records its arguments and returns a chosen exit."""

    exit_code: int = 0
    calls: list[dict[str, object]] = field(default_factory=list)

    def __call__(self, *, profile: str, compact: bool, corpus_resolves: bool) -> int:
        self.calls.append(
            {"profile": profile, "compact": compact, "corpus_resolves": corpus_resolves}
        )
        return self.exit_code


@dataclass
class Row:
    """An `Entry`: one `importlib.metadata.EntryPoint`'s readable half."""

    target: object
    name: str = SERVE_NAME
    value: str = "omniweave_serve.launch:run"
    loads: int = 0

    def load(self) -> object:
        self.loads += 1
        return self.target


def _run(
    tmp_path: Path,
    argv: list[str],
    *,
    body: str = "",
    env: Mapping[str, str] | None = None,
    rows: list[Row] | None = None,
) -> tuple[int, str]:
    (tmp_path / "omniweave.toml").write_text(body, encoding="utf-8")
    environment = {"OMNIWEAVE_HOME": str(tmp_path / "owhome"), **(env or {})}
    err = io.StringIO()
    code = main(
        ["serve", *argv],
        env=environment,
        cwd=tmp_path,
        stderr=err,
        entries=rows if rows is not None else [],
    )
    return code, err.getvalue()


# ---------------------------------------------------------------------------------------------
# what the entry point receives
# ---------------------------------------------------------------------------------------------


def test_the_shipped_default_hands_over_step_5s_three_values(tmp_path: Path) -> None:
    served = Recorder(exit_code=0)
    code, err = _run(tmp_path, ["--mcp"], rows=[Row(served)])
    assert (code, err) == (0, "")
    assert served.calls == [{"profile": "default", "compact": True, "corpus_resolves": False}]


def test_a_declared_default_corpus_resolves(tmp_path: Path) -> None:
    served = Recorder()
    body = HANDBOOK + '[serve]\ndefault_corpus = "handbook"\n'
    _run(tmp_path, ["--mcp"], body=body, rows=[Row(served)])
    assert served.calls[0]["corpus_resolves"] is True


def test_the_flag_beats_the_key_and_the_key_beats_the_default(tmp_path: Path) -> None:
    """02:1155: an Action argument overrides for that call only."""
    by_key, by_flag = Recorder(), Recorder()
    body = '[serve]\nprofile = "full"\ncompact_schemas = false\n'
    _run(tmp_path, ["--mcp"], body=body, rows=[Row(by_key)])
    _run(tmp_path, ["--mcp", "--profile", "default"], body=body, rows=[Row(by_flag)])
    assert by_key.calls[0] == {"profile": "full", "compact": False, "corpus_resolves": False}
    assert by_flag.calls[0]["profile"] == "default"


def test_the_servers_exit_is_the_verbs_exit(tmp_path: Path) -> None:
    code, _ = _run(tmp_path, ["--mcp"], rows=[Row(Recorder(exit_code=InternalError.EXIT))])
    assert code == InternalError.EXIT


# ---------------------------------------------------------------------------------------------
# the refusals, each one line on stderr and nothing handed over
# ---------------------------------------------------------------------------------------------


@pytest.mark.parametrize("argv", [[], ["--mcp", "--http"]])
def test_neither_or_both_transports_is_a_usage_error(tmp_path: Path, argv: list[str]) -> None:
    served = Recorder()
    code, err = _run(tmp_path, argv, rows=[Row(served)])
    assert code == UsageError.EXIT
    assert "exactly one of --mcp (stdio) or --http" in err
    assert not served.calls


def test_http_is_refused_as_not_dispatched(tmp_path: Path) -> None:
    code, err = _run(tmp_path, ["--http"], rows=[Row(Recorder())])
    assert code == InternalError.EXIT
    assert err.startswith("ow: (exit 70): ow serve --http is not dispatched by this build")


@pytest.mark.parametrize(
    "flags",
    [
        ["--host", "0.0.0.0"],  # noqa: S104 -- a string the refusal names, never bound
        ["--port", "8765"],
        ["--path", "/mcp"],
        ["--api-key", "k"],
        ["--stateless"],
        ["--session-timeout", "60"],
    ],
)
def test_a_listener_flag_beside_a_pipe_is_refused_rather_than_ignored(
    tmp_path: Path, flags: list[str]
) -> None:
    served = Recorder()
    code, err = _run(tmp_path, ["--mcp", *flags], rows=[Row(served)])
    assert code == UsageError.EXIT
    assert flags[0] in err
    assert not served.calls


def test_the_listener_flags_are_10_1426s_six(tmp_path: Path) -> None:
    del tmp_path
    assert HTTP_ONLY == ("host", "port", "path", "api_key", "stateless", "session_timeout")


def test_an_unknown_profile_is_refused_naming_both(tmp_path: Path) -> None:
    code, err = _run(tmp_path, ["--mcp", "--profile", "everything"], rows=[Row(Recorder())])
    assert code == UsageError.EXIT
    assert "default, full" in err
    assert "'everything'" in err


def test_a_listed_override_the_listing_cannot_send_is_refused(tmp_path: Path) -> None:
    """D510. `OMNIWEAVE_MCP_LISTED=ow_query` resolves to one tool, and the listing can send the
    profile's four; sending four under a configuration asking for one is 10:788's quiet narrowing
    from the other side."""
    served = Recorder()
    code, err = _run(
        tmp_path, ["--mcp"], env={"OMNIWEAVE_MCP_LISTED": "ow_query"}, rows=[Row(served)]
    )
    assert code == UsageError.EXIT
    assert "OMNIWEAVE_MCP_LISTED" in err
    assert not served.calls


def test_an_override_that_equals_the_profile_is_served(tmp_path: Path) -> None:
    served = Recorder()
    body = '[serve]\nlisted = ["ow_query", "ow_open", "ow_corpora", "ow_add"]\n'
    code, _ = _run(tmp_path, ["--mcp"], body=body, rows=[Row(served)])
    assert code == 0
    assert served.calls


def test_a_missing_server_is_named_before_a_broken_configuration(tmp_path: Path) -> None:
    code, err = _run(tmp_path, ["--mcp"], body="[serve\nbroken", rows=[])
    assert code == CapabilityMissing.EXIT == 64
    assert f"fix: pip install {SERVE_DISTRIBUTION}" in err


def test_a_broken_configuration_is_a_config_error_once_the_server_is_there(
    tmp_path: Path,
) -> None:
    served = Recorder()
    code, _ = _run(tmp_path, ["--mcp"], body="[serve\nbroken", rows=[Row(served)])
    assert code == ConfigError.EXIT
    assert not served.calls


@pytest.mark.parametrize("argv", [["--mcp", "--bogus"], ["--help"]])
def test_argparse_writes_to_stderr_and_never_to_stdout(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], argv: list[str]
) -> None:
    """Stdout is the protocol channel from the moment the server starts, so nothing on this path
    writes there -- `--help` included. A parse error is exit 1 (10:1484), `--help` is 0."""
    code, err = _run(tmp_path, argv, rows=[Row(Recorder())])
    assert code == (0 if argv == ["--help"] else UsageError.EXIT)
    assert err
    assert capsys.readouterr().out == ""


def test_every_refusal_is_one_ascii_line(tmp_path: Path) -> None:
    """10:294's *"on one line, with no traceback"*, and ASCII for D431's piped-stderr reason."""
    for argv in ([], ["--http"], ["--mcp", "--port", "1"], ["--mcp", "--profile", "é"]):
        _, err = _run(tmp_path, argv, rows=[Row(Recorder())])
        assert err.count("\n") == 1, err
        assert err.isascii(), err
        assert "; fix: " in err


# ---------------------------------------------------------------------------------------------
# serve_entry
# ---------------------------------------------------------------------------------------------


def test_no_entry_point_is_capability_missing_naming_the_install() -> None:
    with pytest.raises(CapabilityMissing) as caught:
        serve_entry([Row(Recorder(), name="other")])
    assert caught.value.missing == (SERVE_DISTRIBUTION,)
    assert caught.value.fix == f"pip install {SERVE_DISTRIBUTION}"


def test_two_entry_points_under_one_name_are_refused_and_neither_is_loaded() -> None:
    rows = [Row(Recorder(), value="a:run"), Row(Recorder(), value="b:run")]
    with pytest.raises(ConfigError, match="declared 2 times"):
        serve_entry(rows)
    assert [row.loads for row in rows] == [0, 0]


def test_a_non_callable_entry_point_is_refused() -> None:
    with pytest.raises(ConfigError, match="not callable"):
        serve_entry([Row("not a function")])


def test_the_installed_entry_point_is_the_servers_launcher() -> None:
    """The workspace installs `omniweave-serve`, so the real lookup finds its `run`. A test may
    import both distributions; G4 scans source."""
    from omniweave_serve.launch import run  # noqa: PLC0415

    assert serve_entry() is run


def test_the_lookup_happens_at_call_time_and_not_at_import() -> None:
    """10:286: *"at call time, never at module import"*. `importlib.metadata` is imported inside
    a function body and nowhere at module level, so importing the registry's neighbour costs no
    metadata scan."""
    tree = ast.parse(Path(dispatch.__file__).read_text(encoding="utf-8"))
    top = [node for node in tree.body if isinstance(node, ast.ImportFrom | ast.Import)]
    assert not any(
        isinstance(node, ast.ImportFrom) and (node.module or "").startswith("importlib")
        for node in top
    )
    nested = [
        node
        for function in ast.walk(tree)
        if isinstance(function, ast.FunctionDef)
        for node in ast.walk(function)
        if isinstance(node, ast.ImportFrom) and node.module == "importlib.metadata"
    ]
    assert len(nested) == 1
    assert (SERVE_GROUP, SERVE_NAME) == ("omniweave.serve", "mcp")
