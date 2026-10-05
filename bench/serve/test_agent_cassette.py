"""The `bench.agent` Cassette site: record, replay, refuse (ADR-14 D14.4; 13-quality.md:982)."""

from __future__ import annotations

import dataclasses
import json
import sys
from pathlib import Path
from urllib.parse import quote

import agent_cassette as ca
import models as m
import pytest
from omniweave_core.cassette import MAX_CASSETTE_BYTES, CassetteMode

MODEL_KEY = "anthropic/claude-sonnet-5"


def _request(
    text: str = "notice?", *, arguments: dict[str, object] | None = None
) -> m.ModelRequest:
    use = m.ToolUse("t1", "Grep", arguments or {"pattern": "notice", "path": "/d"})
    return m.ModelRequest(
        system="sys",
        messages=(m.UserText(text), m.AssistantTurn(m.Turn("", (use,))), m.ToolResult("t1", "hit")),
        tools=(m.ToolSpec("Grep", "search", {"type": "object"}),),
        model="claude-sonnet-5",
        temperature=0.0,
        max_tokens=256,
        sampling={"allow_tools": True},
    )


def _never(request: m.ModelRequest) -> m.Turn:
    raise AssertionError(f"a live call was made for {request.model}")


def test_the_key_ignores_argument_order_and_moves_with_every_keyed_input() -> None:
    one, _ = ca.request_key(_request(arguments={"a": 1, "b": 2}), model_key=MODEL_KEY)
    two, _ = ca.request_key(_request(arguments={"b": 2, "a": 1}), model_key=MODEL_KEY)
    assert one == two
    base, _ = ca.request_key(_request(), model_key=MODEL_KEY)
    assert ca.request_key(_request("other"), model_key=MODEL_KEY)[0] != base
    assert ca.request_key(_request(), model_key="openai/qwen3:8b")[0] != base
    _, inputs = ca.request_key(_request(), model_key=MODEL_KEY)
    assert sorted(inputs) == [
        "contract",
        "model_key",
        "payload_digest",
        "prompt_digest",
        "sampling",
        "service",
    ]
    assert inputs["contract"] == ["bench.agent", ca.HARNESS_MAJOR]


def test_allow_records_once_and_required_replays_with_no_provider(tmp_path: Path) -> None:
    turn = m.Turn("Thirty days, per the MSA.")
    recorder = ca.AgentCassette(CassetteMode.ALLOW, tmp_path)
    assert recorder.turn(_request(), model_key=MODEL_KEY, live=lambda _r: turn) == turn
    assert (recorder.live_calls, len(recorder.recorded)) == (1, 1)

    replayer = ca.AgentCassette(CassetteMode.REQUIRED, tmp_path)
    assert replayer.turn(_request(), model_key=MODEL_KEY, live=None) == turn
    assert (replayer.live_calls, replayer.hits) == (0, recorder.recorded)


def test_a_required_miss_is_ow_q_004_naming_the_record_path_and_never_calls_live(
    tmp_path: Path,
) -> None:
    cassette = ca.AgentCassette(CassetteMode.REQUIRED, tmp_path)
    with pytest.raises(ca.CassetteMissError) as caught:
        cassette.turn(_request(), model_key=MODEL_KEY, live=_never)
    assert "OW-Q-004" in str(caught.value)
    assert "cassette = allow" in str(caught.value)
    assert cassette.live_calls == 0


def test_off_calls_live_and_writes_nothing(tmp_path: Path) -> None:
    cassette = ca.AgentCassette(CassetteMode.OFF, tmp_path)
    cassette.turn(_request(), model_key=MODEL_KEY, live=lambda _r: m.Turn("x"))
    assert cassette.live_calls == 1
    assert not any(tmp_path.rglob("*.json"))


def test_a_record_holds_the_key_inputs_and_the_turn_and_no_header(tmp_path: Path) -> None:
    cassette = ca.AgentCassette(CassetteMode.ALLOW, tmp_path)
    cassette.turn(_request(), model_key=MODEL_KEY, live=lambda _r: m.Turn("x"))
    (path,) = tmp_path.rglob("*.json")
    assert path.parent.parent.name == "agent"
    record = json.loads(path.read_text(encoding="utf-8"))
    assert record["seam"] == "bench.agent"
    assert record["prompt_version"] == ca.PROMPT_VERSION
    assert sorted(record) == [
        "contract_major",
        "inputs",
        "key",
        "prompt_version",
        "record_version",
        "seam",
        "turn",
    ]
    assert "x-api-key" not in path.read_text(encoding="utf-8").casefold()


def test_a_stale_prompt_version_is_a_miss_and_not_a_hit(tmp_path: Path) -> None:
    ca.AgentCassette(CassetteMode.ALLOW, tmp_path).turn(
        _request(), model_key=MODEL_KEY, live=lambda _r: m.Turn("x")
    )
    (path,) = tmp_path.rglob("*.json")
    record = json.loads(path.read_text(encoding="utf-8"))
    record["prompt_version"] = "agent-prompt/0"
    path.write_text(json.dumps(record), encoding="utf-8")
    with pytest.raises(ca.CassetteMissError):
        ca.AgentCassette(CassetteMode.REQUIRED, tmp_path).turn(
            _request(), model_key=MODEL_KEY, live=None
        )


def test_an_oversize_recording_is_refused_at_record_time_and_nothing_is_written(
    tmp_path: Path,
) -> None:
    huge = m.Turn("x" * (MAX_CASSETTE_BYTES + 1))
    cassette = ca.AgentCassette(CassetteMode.ALLOW, tmp_path)
    with pytest.raises(ca.CassetteOversizeError, match="OW-Q-017"):
        cassette.turn(_request(), model_key=MODEL_KEY, live=lambda _r: huge)
    assert not any(tmp_path.rglob("*.json"))


def _recorded(root: Path) -> Path:
    ca.AgentCassette(CassetteMode.ALLOW, root).turn(
        _request(), model_key=MODEL_KEY, live=lambda _r: m.Turn("Thirty days.")
    )
    (path,) = root.rglob("*.json")
    return path


def test_the_audit_passes_a_store_as_recorded_and_the_committed_one(tmp_path: Path) -> None:
    """D650: the `golden` job's Cassette step, and the committed recordings it runs over."""
    path = _recorded(tmp_path)
    assert ca.audit(tmp_path) == (1, path.stat().st_size, [])
    count, _total, problems = ca.audit()
    assert problems == []
    assert count > 0


def test_the_audit_names_each_way_a_store_breaks_without_a_model(tmp_path: Path) -> None:
    """Moved, retyped, re-keyed, hand-edited, foreign: each is a line naming its file."""
    path = _recorded(tmp_path)
    record = json.loads(path.read_text(encoding="utf-8"))

    moved = path.parent.parent / "ff" / path.name
    moved.parent.mkdir()
    path.rename(moved)
    assert any("filed away from its key" in line for line in ca.audit(tmp_path)[2])
    moved.rename(path)

    record["inputs"]["model_key"] = "openai/gpt-5-mini"
    path.write_bytes(ca._encode(record))
    assert any("not the sha256_canonical" in line for line in ca.audit(tmp_path)[2])

    record = json.loads(_recorded(tmp_path / "again").read_text(encoding="utf-8"))
    path.write_text(json.dumps(record), encoding="utf-8")
    assert any("hand edit" in line for line in ca.audit(tmp_path)[2])

    path.write_text("{", encoding="utf-8")
    (path.parent / "notes.txt").write_text("x", encoding="utf-8")
    problems = ca.audit(tmp_path)[2]
    assert any("not a record" in line for line in problems)
    assert any("notes.txt: not a recording" in line for line in problems)


def test_audit_cassettes_is_the_golden_jobs_step_and_exits_on_a_problem(tmp_path: Path) -> None:
    import run  # noqa: PLC0415 -- the CLI half

    lines: list[str] = []
    _recorded(tmp_path)
    assert run.main(["--audit-cassettes", "--cassettes", str(tmp_path)], out=lines.append) == 0
    assert lines[-1].startswith("bench/serve: cassette audit passed: 1 recordings")
    (tmp_path / "agent" / "stray.bin").write_bytes(b"x")
    assert run.main(["--audit-cassettes", "--cassettes", str(tmp_path)], out=lines.append) == 1


def _at(root: Path) -> m.ModelRequest:
    """One conversation, as it reads with the corpora under `root`."""
    docs = (root / "data_room-full-0123456789ab" / "project" / "docs").resolve().as_posix()
    use = m.ToolUse("t1", "Grep", {"pattern": "revenue", "path": docs})
    return m.ModelRequest(
        system=f"You are answering a question about the documents in the folder {docs}.",
        messages=(
            m.UserText("revenue?"),
            m.AssistantTurn(m.Turn("", (use,))),
            m.ToolResult("t1", f"{docs}/finance/q4.xlsx\n" + docs.replace("/", "\\") + "\a.pdf"),
        ),
        tools=(m.ToolSpec("Grep", "search", {"type": "object"}),),
        model="claude-sonnet-5",
        temperature=None,
        max_tokens=256,
    )


def test_a_recording_replays_under_another_machines_corpora_folder(tmp_path: Path) -> None:
    """D650: the key holds no `--cache` path, and a replayed turn names the replaying folder."""
    here, there = tmp_path / "mine" / "bench-cache", tmp_path / "Theirs Home" / "cache"
    store = tmp_path / "cassettes"
    reading = (here / "data_room-full-0123456789ab" / "project" / "docs").resolve().as_posix()
    answer = m.Turn("", (m.ToolUse("t2", "Read", {"file_path": f"{reading}/finance/q4.xlsx"}),))
    recorder = ca.AgentCassette(CassetteMode.ALLOW, store, corpora=here)
    recorder.turn(_at(here), model_key=MODEL_KEY, live=lambda _r: answer)
    (path,) = store.rglob("*.json")
    assert str(here.resolve().as_posix()) not in path.read_text(encoding="utf-8")
    assert ca.CORPORA in path.read_text(encoding="utf-8")

    replayer = ca.AgentCassette(CassetteMode.REQUIRED, store, corpora=there)
    (use,) = replayer.turn(_at(there), model_key=MODEL_KEY, live=None).tool_uses
    assert use.arguments["file_path"] == (
        f"{there.resolve().as_posix()}/data_room-full-0123456789ab/project/docs/finance/q4.xlsx"
    )
    assert ca.audit(store)[2] == []


def test_a_recorded_turn_keeps_the_spelling_it_named_the_folder_in(tmp_path: Path) -> None:
    """D651: omniweave writes paths case-folded on Windows, and an answer that echoes one must
    replay as it was recorded, under this folder or another machine's."""
    here, there = tmp_path / "Mine" / "bench-cache", tmp_path / "Theirs" / "Cache"
    store = tmp_path / "cassettes"
    base = here.resolve().as_posix()
    folded = base.casefold() if sys.platform == "win32" else base
    text = f"see {folded}/a.pdf, {base.replace('/', chr(92))}{chr(92)}b.pdf and {quote(base)}/c"
    recorder = ca.AgentCassette(CassetteMode.ALLOW, store, corpora=here)
    recorder.turn(_at(here), model_key=MODEL_KEY, live=lambda _r: m.Turn(text))
    assert ca.AgentCassette(CassetteMode.REQUIRED, store, corpora=here).turn(
        _at(here), model_key=MODEL_KEY, live=None
    ) == m.Turn(text)

    moved = there.resolve().as_posix()
    want = text.replace(folded, moved.casefold() if sys.platform == "win32" else moved)
    want = want.replace(base.replace("/", chr(92)), moved.replace("/", chr(92)))
    want = want.replace(quote(base), quote(moved))
    replayed = ca.AgentCassette(CassetteMode.REQUIRED, store, corpora=there).turn(
        _at(there), model_key=MODEL_KEY, live=None
    )
    assert replayed == m.Turn(want)


def test_a_store_command_is_one_key_on_every_platform_and_replays_as_this_ones() -> None:
    """D653: an answer about an encrypted file names the store command of the machine it ran
    on; the key holds none of the three, and a replayed turn prints this machine's."""
    from omniweave_core.host import keystore  # noqa: PLC0415

    keys = set()
    for platform in ("win32", "darwin", "linux"):
        text = f"store it with `{keystore.store_command('amendment-1', platform)}`, then rerun"
        request = dataclasses.replace(
            _request(), messages=(m.UserText("q"), m.AssistantTurn(m.Turn(text)))
        )
        keys.add(ca.request_key(request, model_key=MODEL_KEY)[0])
        assert ca._local(ca._tagged(text, None), None) == (
            f"store it with `{keystore.store_command('amendment-1')}`, then rerun"
        )
    assert len(keys) == 1


def _answer(root: str, platform: str) -> str:
    """An Answer naming a gap under `root` with `platform`'s store command, its own length filled
    in the way `render._substitute` fills it."""
    from omniweave_core.host import keystore  # noqa: PLC0415

    sentinel = "\x00" * 5
    body = (
        f"ow/1 degraded corpus=docs@1 fresh blocks=7/100 docs=4/17 chars={sentinel}/12000\n"
        f"budget             = {sentinel}/12000 chars · call 1 of 1\n"
        f"> parse_gap_in_scope: {root}/docs/a.pdf: refused as encrypted; store it with "
        f"`{keystore.store_command('a', platform)}`\n"
    )
    return body.replace(sentinel, f"{len(body):>5}")


def test_an_answers_own_length_is_one_key_on_every_machine(tmp_path: Path) -> None:
    """D653: `chars=` counts the corpus folder and the store command, so the same Answer printed
    a different length on each machine; a key spells it as the length of the neutral document."""
    keys = set()
    for root, platform in ((tmp_path / "short", "linux"), (tmp_path / ("long" * 30), "win32")):
        text = _answer(root.resolve().as_posix(), platform)
        request = dataclasses.replace(
            _request(), messages=(m.UserText("q"), m.ToolResult("t1", text))
        )
        keys.add(ca.request_key(request, model_key=MODEL_KEY, corpora=root)[0])
        assert "docs=4/17" in ca._neutral(text, ca._spellings(root))
    assert len(keys) == 1


@pytest.mark.parametrize("tag", ["{bench-cache|casefold}", "{bench-cache|casefold|backslash}"])
def test_a_case_folded_turn_recorded_on_windows_replays_as_a_path_on_linux(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, tag: str
) -> None:
    """D654: `_forms` keeps a case-folded spelling apart only on Windows, so a Linux replay left
    `{bench-cache|casefold}` in the model's tool call, the agent sent the tag back, and the next
    request's key missed (three conversations of the recorded sets). On Linux the folder has one
    spelling, so the tag is that, and the next key spells it `CORPORA` as on Windows."""
    monkeypatch.setattr(ca.sys, "platform", "linux")
    root = tmp_path / "Bench-Cache"
    root.mkdir()
    local = ca._local(f"open {tag}/docs/tax.docx", root)
    assert "{bench-cache" not in local
    assert ca._neutral(local, ca._spellings(root)) == f"open {ca.CORPORA}/docs/tax.docx"
