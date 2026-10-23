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
        "sent_requests": 0,
        "sent_spans": 0,
        "halted": "",
    }


# --- refusals --------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("argv", "says"),
    [
        (("--file", "x.jsonl"), "needs --run"),
        (("--run", RUN), "takes --file, --otlp or --dry-run"),
        (("--run", RUN, "--file", "x.jsonl", "--otlp", "http://c"), "one destination"),
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


# --- --otlp (D948) ---------------------------------------------------------------------------

ENDPOINT = "https://user:secret@collector.internal:4318"


class _Collector:
    """A `Transport` that answers every POST with one status and keeps the URLs."""

    def __init__(self, status: int = 200) -> None:
        self.status = status
        self.urls: list[str] = []

    def post(self, url: str, body: bytes, headers: object) -> object:
        from omniweave_serve.export import Response  # noqa: PLC0415

        del body, headers
        self.urls.append(url)
        return Response(self.status, "OK" if self.status == 200 else "Unavailable")


def _collector(monkeypatch: pytest.MonkeyPatch, status: int = 200) -> _Collector:
    import omniweave_serve.entry as entry_module  # noqa: PLC0415

    collector = _Collector(status)
    monkeypatch.setattr(entry_module, "UrllibTransport", lambda: collector)
    monkeypatch.setattr(entry_module.time, "sleep", lambda _seconds: None)
    return collector


def test_otlp_sends_the_run_to_the_collector_and_never_prints_the_endpoint(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    project = _project(tmp_path)
    collector = _collector(monkeypatch)
    code, out, err = _run(project, "--run", RUN, "--otlp", ENDPOINT)
    assert (code, err) == (0, "")
    assert collector.urls == [f"{ENDPOINT}/v1/traces"]
    assert "sent 1 request(s), 1 span(s), to the collector" in out
    assert "secret" not in out
    assert "collector.internal" not in out


def test_with_no_destination_the_configured_endpoint_is_the_collector(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Ruling 2: 15:260's `[observe] otlp_endpoint`, honoured by this verb alone."""
    project = _project(tmp_path)
    settings = project / "omniweave.toml"
    settings.write_text(
        settings.read_text(encoding="utf-8") + f'[observe]\notlp_endpoint = "{ENDPOINT}"\n',
        encoding="utf-8",
    )
    collector = _collector(monkeypatch)
    code, _, err = _run(project, "--run", RUN)
    assert (code, err) == (0, "")
    assert collector.urls == [f"{ENDPOINT}/v1/traces"]


def test_a_collector_that_never_answers_is_a_resource_limit_naming_the_offset(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Ruling 6: exit 1, `ResourceLimit`'s symbol, the committed offset, and no endpoint."""
    project = _project(tmp_path)
    collector = _collector(monkeypatch, status=503)
    code, out, err = _run(project, "--run", RUN, "--otlp", ENDPOINT)
    assert code == 1
    assert out == ""
    assert err.startswith("ow: OW_RESOURCE_LIMIT: trace export stopped after 4 attempts")
    assert "the cursor is committed at nothing" in err
    assert "secret" not in err
    assert len(collector.urls) == 4


def test_a_dry_run_beside_otlp_rehearses_and_sends_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    project = _project(tmp_path)
    collector = _collector(monkeypatch)
    code, out, _ = _run(project, "--run", RUN, "--otlp", ENDPOINT, "--dry-run", "--print-payload")
    assert code == 0
    assert collector.urls == []
    assert len(out.splitlines()) == 1
    assert json.loads(out)["resourceSpans"]


# --- ow trace stat (D949) --------------------------------------------------------------------


def _stat(cwd: Path, *argv: str) -> tuple[int, str, str]:
    out, err = io.StringIO(), io.StringIO()
    env = {"OMNIWEAVE_HOME": str(cwd.parent / "home")}
    code = verb.main(["trace", "stat", *argv], cwd=cwd, env=env, stdout=out, stderr=err)
    return code, out.getvalue(), err.getvalue()


def test_stat_prints_a_line_per_shard_the_kinds_the_spans_and_the_drops(tmp_path: Path) -> None:
    """Ruling 7 over the shard a real `RunTrace` wrote."""
    project = _project(tmp_path)
    code, out, err = _stat(project, "--run", RUN)
    assert (code, err) == (0, "")
    lines = out.splitlines()
    assert lines[0] == "ow trace stat  1 run(s), 1 shard(s)"
    assert lines[1].startswith(f"  shard   {RUN}.ndjson  3 record(s), ")
    assert lines[1].endswith(" uncompressed, ratio 1.00")
    assert lines[2] == "  kinds   run.end 1, run.start 1, unit.failed 1"
    assert lines[3].startswith("  span    run  1 span(s), ")
    assert lines[4] == "  dropped 0 record(s)"


def test_stat_with_no_run_reads_every_run_and_writes_nothing(tmp_path: Path) -> None:
    project = _project(tmp_path)
    before = sorted(path.name for path in project.rglob("*"))
    code, out, _ = _stat(project, "--render", "json")
    assert code == 0
    row = json.loads(out)
    assert row["runs"] == [RUN]
    assert [kind["kind"] for kind in row["kinds"]] == ["run.end", "run.start", "unit.failed"]
    assert sorted(path.name for path in project.rglob("*")) == before


def test_stat_of_an_unknown_run_is_not_found(tmp_path: Path) -> None:
    project = _project(tmp_path)
    code, _, err = _stat(project, "--run", "r_nope")
    assert code == 2
    assert "run r_nope has no event shard at" in err


def test_stat_with_no_project_is_not_found(tmp_path: Path) -> None:
    code, _, err = _stat(tmp_path)
    assert code == 2
    assert "has no event shard: no project is in view" in err


def test_a_malformed_stat_reply_is_an_internal_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    project = _project(tmp_path)
    reply = {"runs": [], "shards": [{"name": "x"}], "kinds": [], "spans": [], "dropped": 0}
    monkeypatch.setattr(verb, "trace_entry", lambda _name: lambda **_: reply)
    code, _, err = _stat(project, "--run", RUN)
    assert code == 70
    assert "stat entry point returned an unreadable report" in err


# --- ow trace tree (D950) --------------------------------------------------------------------


def _tree(cwd: Path, *argv: str) -> tuple[int, str, str]:
    out, err = io.StringIO(), io.StringIO()
    env = {"OMNIWEAVE_HOME": str(cwd.parent / "home")}
    code = verb.main(["trace", "tree", *argv], cwd=cwd, env=env, stdout=out, stderr=err)
    return code, out.getvalue(), err.getvalue()


def test_tree_prints_the_run_span_and_the_failure_under_it(tmp_path: Path) -> None:
    """Ruling 8 over the shard a real `RunTrace` wrote: a `unit.failed` is a point under the run."""
    project = _project(tmp_path)
    code, out, err = _tree(project, RUN)
    assert (code, err) == (0, "")
    header, run, failed = out.splitlines()
    assert header == f"ow trace tree  run {RUN}, 1 span(s)"
    assert run.startswith("  run  ")
    assert run.endswith(" ms  partial")
    assert failed == "    unit.failed  driver_bug  u/a.txt"


def test_tree_render_json_is_the_report(tmp_path: Path) -> None:
    project = _project(tmp_path)
    code, out, _ = _tree(project, RUN, "--render", "json", "--depth", "0")
    assert code == 0
    row = json.loads(out)
    assert (row["run_id"], row["spans"]) == (RUN, 1)
    assert [(node["name"], node["depth"]) for node in row["nodes"]] == [("run", 0)]


@pytest.mark.parametrize("flag", ["--depth", "--slow"])
def test_tree_refuses_a_negative_count(tmp_path: Path, flag: str) -> None:
    project = _project(tmp_path)
    code, _, err = _tree(project, RUN, flag, "-1")
    assert code == 1
    assert f"{flag} is -1; it is a count and never below 0" in err


def test_tree_of_an_unknown_run_is_not_found(tmp_path: Path) -> None:
    project = _project(tmp_path)
    code, _, err = _tree(project, "r_nope")
    assert code == 2
    assert "run r_nope has no event shard at" in err


def test_a_malformed_tree_reply_is_an_internal_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    project = _project(tmp_path)
    reply = {"nodes": [{"name": "run"}], "spans": 1}
    monkeypatch.setattr(verb, "trace_entry", lambda _name: lambda **_: reply)
    code, _, err = _tree(project, RUN)
    assert code == 70
    assert "tree entry point returned an unreadable report" in err


# --- ow trace prune (D951) -------------------------------------------------------------------


def _prune(cwd: Path, *argv: str) -> tuple[int, str, str]:
    out, err = io.StringIO(), io.StringIO()
    env = {"OMNIWEAVE_HOME": str(cwd.parent / "home")}
    code = verb.main(["trace", "prune", *argv], cwd=cwd, env=env, stdout=out, stderr=err)
    return code, out.getvalue(), err.getvalue()


def _aged_project(tmp_path: Path, *, days: int) -> tuple[Path, Path]:
    """`_project`'s shard, last written `days` ago by the machine's own clock, as prune reads it."""
    import os  # noqa: PLC0415
    import time  # noqa: PLC0415

    project = _project(tmp_path)
    (shard,) = (project / ".omniweave" / "events").glob("*.ndjson")
    stamp = time.time_ns() - days * 86_400 * 1_000_000_000
    os.utime(shard, ns=(stamp, stamp))
    return project, shard


def test_prune_removes_a_shard_older_than_the_shipped_fourteen_days(tmp_path: Path) -> None:
    project, shard = _aged_project(tmp_path, days=15)
    size = shard.stat().st_size
    code, out, err = _prune(project)
    assert (code, err) == (0, "")
    assert not shard.exists()
    assert out.splitlines() == [
        f"  removed  {shard.name}",
        f"ow trace prune  removed 1 shard(s), {size} bytes, older than 14d; kept 0",
    ]


def test_prune_dry_run_and_a_longer_retention_keep_the_shard(tmp_path: Path) -> None:
    project, shard = _aged_project(tmp_path, days=15)
    code, out, _ = _prune(project, "--dry-run")
    assert code == 0
    assert out.startswith(f"  would remove  {shard.name}\n")
    assert shard.exists()
    settings = project / "omniweave.toml"
    settings.write_text(
        settings.read_text(encoding="utf-8") + "[observe]\nretain_days = 30\n", encoding="utf-8"
    )
    code, out, _ = _prune(project, "--render", "json")
    assert code == 0
    row = json.loads(out)
    assert (row["removed"], row["kept"], row["older_than_ms"]) == ([], 1, 30 * 86_400_000)
    assert shard.exists()


def test_prune_older_than_is_a_duration_or_refused(tmp_path: Path) -> None:
    project, shard = _aged_project(tmp_path, days=2)
    code, _, err = _prune(project, "--older-than", "soon")
    assert code == 1
    assert "'soon' is not a duration" in err
    code, out, _ = _prune(project, "--older-than", "1d")
    assert code == 0
    assert "older than 1d; kept 0" in out
    assert not shard.exists()
