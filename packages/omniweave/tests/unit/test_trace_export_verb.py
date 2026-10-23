"""`ow trace export`: the verb, its entry point, and each exit its docstring rules. D947.

The verb runs in-process through `omniweave.surface.trace.main`, against a run shard written under
`tmp_path` by `omniweave.run.trace.RunTrace`, the writer a real `ow add` uses (D941). The work
happens in `omniweave-serve`, across the `[omniweave.trace] export` entry point the workspace
installs. The refusal when that entry point is missing is tested by handing `trace_entry()` no
rows, as the eval verb's tests do.
"""

from __future__ import annotations

import io
import json
from typing import TYPE_CHECKING

import omniweave.__main__ as launcher
import pytest
from omniweave.run.trace import RunTrace
from omniweave.surface import dispatch
from omniweave.surface import trace as verb
from omniweave_core.clock import SystemClock
from omniweave_core.config import load
from omniweave_core.errors import CapabilityMissing

if TYPE_CHECKING:
    from pathlib import Path

RUN = "r_01J0000000000000000000000"
CONFIG = '[corpora.docs]\npath = ".omniweave/docs.owstore"\n'


def _project(root: Path) -> Path:
    """A project with one recorded run: `run.start`, a `unit.failed`, `run.end`."""
    project = root / "project"
    project.mkdir()
    (project / "omniweave.toml").write_text(CONFIG, encoding="utf-8")
    config = load(cwd=project, env={"OMNIWEAVE_HOME": str(root / "home")})
    trace = RunTrace.open(config, run_id=RUN, worker="host:42:12.5", clock=SystemClock())
    assert trace is not None
    trace.start(
        trigger="cli", argv_digest="a" * 64, config_digest="b" * 64, semantic_digest="c" * 64,
        generation=1,
    )  # fmt: skip
    trace.failed([("u/a.txt", "parse.text.x", "driver_bug", "ValueError at d.py:3 in p")])
    trace.end(status="partial", units=1, failures=1, micros=0)
    trace.close()
    return project


def _run(cwd: Path, *argv: str) -> tuple[int, str, str]:
    out, err = io.StringIO(), io.StringIO()
    env = {"OMNIWEAVE_HOME": str(cwd.parent / "home")}
    code = verb.main(["trace", "export", *argv], cwd=cwd, env=env, stdout=out, stderr=err)
    return code, out.getvalue(), err.getvalue()


# --- export ----------------------------------------------------------------------------------


def test_file_writes_the_run_span_as_one_request_line(tmp_path: Path) -> None:
    project = _project(tmp_path)
    code, out, err = _run(project, "--run", RUN, "--file", "spans.jsonl")
    assert (code, err) == (0, "")
    lines = (project / "spans.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    (span,) = json.loads(lines[0])["resourceSpans"][0]["scopeSpans"][0]["spans"]
    assert span["name"] == "run"
    assert out == (
        f"run {RUN}: 1 span(s) in 1 request(s) from 1 shard(s), wrote spans.jsonl; "
        "not exported: 1 point record(s)\n"
    )


def test_the_file_names_no_unit_and_carries_no_message(tmp_path: Path) -> None:
    """15:246 and 14:802: span metadata only. The failure's unit and message are a point record,
    and a point record is counted and not written (`entry`'s ruling 3)."""
    project = _project(tmp_path)
    _run(project, "--run", RUN, "--file", "spans.jsonl")
    text = (project / "spans.jsonl").read_text(encoding="utf-8")
    assert "u/a.txt" not in text
    assert "ValueError" not in text


def test_a_dry_run_prints_the_bodies_the_file_would_hold_and_writes_nothing(
    tmp_path: Path,
) -> None:
    project = _project(tmp_path)
    _run(project, "--run", RUN, "--file", "spans.jsonl")
    before = sorted(path.name for path in project.rglob("*"))
    code, out, _ = _run(project, "--run", RUN, "--dry-run", "--print-payload")
    assert code == 0
    assert out.splitlines() == (project / "spans.jsonl").read_text(encoding="utf-8").splitlines()
    assert sorted(path.name for path in project.rglob("*")) == before


def test_render_json_prints_one_object_with_the_counts(tmp_path: Path) -> None:
    project = _project(tmp_path)
    code, out, _ = _run(project, "--run", RUN, "--dry-run", "--render", "json")
    assert code == 0
    row = json.loads(out)
    assert row == {
        "run_id": RUN,
        "shards": [f"{RUN}.ndjson"],
        "spans": 1,
        "batches": 1,
        "points": 1,
        "unterminated": 0,
        "orphaned": 0,
        "file": "",
        "payloads": 1,
    }


# --- refusals --------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("argv", "says"),
    [
        (("--file", "x.jsonl"), "needs --run"),
        (("--run", RUN), "takes --file or --dry-run, one of the two"),
        (("--run", RUN, "--file", "x.jsonl", "--dry-run"), "one of the two"),
        (("--run", RUN, "--file", "x.jsonl", "--print-payload"), "what --dry-run would send"),
        (("--run", RUN, "--dry-run", "--render", "jsonl"), "--render jsonl is parsed and not"),
    ],
)
def test_a_usage_error_names_the_rule_and_writes_nothing(
    tmp_path: Path, argv: tuple[str, ...], says: str
) -> None:
    project = _project(tmp_path)
    before = sorted(path.name for path in project.rglob("*"))
    code, _, err = _run(project, *argv)
    assert code == 1
    assert says in err
    assert sorted(path.name for path in project.rglob("*")) == before


def test_an_unknown_run_is_not_found_and_no_file_is_written(tmp_path: Path) -> None:
    """Ruling 3."""
    project = _project(tmp_path)
    code, _, err = _run(project, "--run", "r_nope", "--file", "x.jsonl")
    assert code == 2
    assert "run r_nope has no event shard at" in err
    assert not (project / "x.jsonl").exists()


def test_no_project_is_not_found(tmp_path: Path) -> None:
    code, _, err = _run(tmp_path, "--run", RUN, "--dry-run")
    assert code == 2
    assert f"run {RUN} has no event shard: no project is in view" in err


def test_without_omniweave_serve_the_verb_is_capability_missing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Ruling 5: exit 64 and the install command."""
    project = _project(tmp_path)
    monkeypatch.setattr(dispatch, "_installed", lambda *_: [])
    code, _, err = _run(project, "--run", RUN, "--dry-run")
    assert code == 64
    assert "ow trace export needs omniweave-serve, which is not installed" in err
    assert "fix: pip install omniweave-serve" in err


@pytest.mark.parametrize("reply", [{"shards": "x"}, {"shards": [], "payloads": [], "file": ""}])
def test_a_malformed_entry_point_reply_is_an_internal_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, reply: dict[str, object]
) -> None:
    project = _project(tmp_path)
    monkeypatch.setattr(verb, "trace_entry", lambda _name: lambda **_: reply)
    code, _, err = _run(project, "--run", RUN, "--dry-run")
    assert code == 70
    assert "returned an unreadable report" in err


def test_the_launcher_routes_trace_to_the_verb(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.chdir(tmp_path)
    assert launcher.main(["trace", "export", "--run", RUN, "--dry-run"]) == 2
    assert "has no event shard" in capsys.readouterr().err


# --- trace_entry() ---------------------------------------------------------------------------


def test_trace_entry_refuses_by_naming_the_group_and_the_distribution() -> None:
    with pytest.raises(CapabilityMissing) as missing:
        dispatch.trace_entry("export", [])
    assert missing.value.missing == ("omniweave-serve",)
    assert "no [omniweave.trace] export entry point" in str(missing.value)


def test_the_workspace_installs_the_export_entry_point() -> None:
    from omniweave_serve.entry import export  # noqa: PLC0415

    assert dispatch.trace_entry("export") is export
