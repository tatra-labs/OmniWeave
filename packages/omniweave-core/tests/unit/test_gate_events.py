"""G20 against the committed tree, and against four trees that should fail it.

A gate that has only ever been run on a clean checkout is a gate nobody has tested. Each of its four
checks gets a negative case built by mutating a copy of the real artefacts -- a hand-edited row, a
schema whose enum has drifted, a row with its `level` removed, and a vocabulary with a published
kind deleted -- and each asserts that the failure names the edit that clears it.

The append-only check is the one that cannot be exercised against this repository as it stands:
there is no tag, so `check_append_only` reports `SKIP` and the gate is green. That is the correct
behaviour and it is asserted, but a `SKIP` that is never followed by a real comparison is a check
nobody has seen work -- so `test_a_published_kind_that_disappears_is_a_finding` drives the same
comparison directly with a synthetic "published" list.
"""

from __future__ import annotations

import json
import sys
import tomllib
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pytest

if TYPE_CHECKING:
    from collections.abc import Iterator

REPO = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(REPO / "tools"))

import gate_events  # noqa: E402
import gen_events  # noqa: E402

EVENTS_PATH = REPO / "tools" / "events.toml"
SCHEMA_PATH = REPO / "schema" / "event-v1.json"


@pytest.fixture
def committed(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Iterator[Path]:
    """A writable copy of the two committed artefacts, with the gate pointed at it.

    The gate's own module constants are repointed rather than the files edited in place: a test that
    mutated `tools/events.toml` and crashed would leave the working tree failing G20 for everybody.
    """
    events = tmp_path / "events.toml"
    schema = tmp_path / "event-v1.json"
    events.write_bytes(EVENTS_PATH.read_bytes())
    schema.write_bytes(SCHEMA_PATH.read_bytes())
    monkeypatch.setattr(gate_events, "EVENTS_PATH", events)
    monkeypatch.setattr(gate_events, "SCHEMA_PATH", schema)
    monkeypatch.setattr(gen_events, "OUTPUT_PATH", events)
    monkeypatch.setattr(gate_events, "REPO", tmp_path)
    yield tmp_path


def _rows(path: Path) -> list[dict[str, Any]]:
    return list(tomllib.loads(path.read_text(encoding="utf-8"))["event"])


def test_the_gate_passes_on_the_committed_tree(capsys: pytest.CaptureFixture[str]) -> None:
    assert gate_events.main([]) == 0
    out = capsys.readouterr().out
    assert "G20 ok" in out
    assert "65 event kinds" in out


def test_the_committed_file_is_its_generators_output_byte_for_byte() -> None:
    """T-GENERATED: *"byte-identical to its generator's output"* (02-architecture.md section 2)."""
    assert EVENTS_PATH.read_bytes() == gen_events.render().encode("utf-8")
    assert gate_events.check_generated() == ()


def test_a_hand_edited_row_fails_check_one(committed: Path) -> None:
    """Correct and hand-written still fails: the file is generated, and that is the whole rule."""
    events = committed / "events.toml"
    events.write_text(
        events.read_text(encoding="utf-8").replace('level = "warn"', 'level = "error"', 1),
        encoding="utf-8",
    )
    findings = gate_events.check_generated()
    assert len(findings) == 1
    assert "byte-identical" in findings[0].headline
    assert "uv run tools/gen_events.py" in findings[0].render()


def test_a_schema_whose_enum_has_drifted_fails_check_two(committed: Path) -> None:
    """The two COMMITTED artefacts are compared to each other, never each to the Python."""
    schema = committed / "event-v1.json"
    document = json.loads(schema.read_text(encoding="utf-8"))
    document["properties"]["kind"]["enum"] = document["properties"]["kind"]["enum"][:-1]
    schema.write_text(json.dumps(document, indent=2), encoding="utf-8")
    findings = gate_events.check_schema_agrees()
    assert len(findings) == 1
    assert "disagree about the vocabulary" in findings[0].headline
    assert "call.end" in findings[0].render()


def test_a_reordered_schema_enum_fails_even_with_the_same_members(committed: Path) -> None:
    """Same members, different order: append order is not decoration (charter.md:4458)."""
    schema = committed / "event-v1.json"
    document = json.loads(schema.read_text(encoding="utf-8"))
    kinds = document["properties"]["kind"]["enum"]
    document["properties"]["kind"]["enum"] = [kinds[1], kinds[0], *kinds[2:]]
    schema.write_text(json.dumps(document, indent=2), encoding="utf-8")
    findings = gate_events.check_schema_agrees()
    assert len(findings) == 1
    assert "different order" in findings[0].render()


def test_a_kind_with_no_closed_enum_at_all_fails_check_two(committed: Path) -> None:
    """A `kind: str` would leave the language-neutral contract saying "any string"."""
    schema = committed / "event-v1.json"
    document = json.loads(schema.read_text(encoding="utf-8"))
    document["properties"]["kind"] = {"type": "string"}
    schema.write_text(json.dumps(document, indent=2), encoding="utf-8")
    findings = gate_events.check_schema_agrees()
    assert len(findings) == 1
    assert "no closed `enum`" in findings[0].headline


def test_a_row_with_no_level_fails_check_three(committed: Path) -> None:
    """15-observability.md:341's not-an-append, checked on the file rather than trusted."""
    events = committed / "events.toml"
    text = events.read_text(encoding="utf-8")
    events.write_text(
        text.replace('kind = "degrade"\nlevel = "warn"\n', 'kind = "degrade"\n', 1),
        encoding="utf-8",
    )
    findings = gate_events.check_levels()
    assert len(findings) == 1
    assert findings[0].headline.startswith("degrade declares no level")


def test_a_sixth_level_fails_check_three(committed: Path) -> None:
    events = committed / "events.toml"
    events.write_text(
        events.read_text(encoding="utf-8").replace('level = "warn"', 'level = "critical"', 1),
        encoding="utf-8",
    )
    findings = gate_events.check_levels()
    assert len(findings) == 1
    assert "'critical'" in findings[0].headline
    assert gate_events.LEVELS == ("debug", "info", "notice", "warn", "error")


def test_every_committed_row_declares_one_of_the_five_levels() -> None:
    declared = {str(row["level"]) for row in _rows(EVENTS_PATH)}
    assert declared <= set(gate_events.LEVELS)
    assert all("level" in row for row in _rows(EVENTS_PATH))
    assert gate_events.check_levels() == ()


def test_no_previous_tag_skips_rather_than_passing_silently(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """A repository with nothing published has removed nothing, and the line says so."""
    findings, note = gate_events.check_append_only()
    assert findings == ()
    assert note.startswith(("SKIP", "ok against"))
    gate_events.main([])
    assert "G20 append-only:" in capsys.readouterr().out


def test_a_published_kind_that_disappears_is_a_finding(monkeypatch: pytest.MonkeyPatch) -> None:
    """The comparison the `SKIP` above defers, driven directly so it is not untested.

    15:283-286: *"A row is never removed and a `kind` is never reused: an event kind is a name a
    dashboard, a runbook and a test all hard-code, so retiring one silently breaks three
    consumers."*
    """
    published = (*gate_events.kinds_in(EVENTS_PATH)[:10], "cache.warm")
    monkeypatch.setattr(gate_events, "previous_tag", lambda: "v0.1.0")
    monkeypatch.setattr(gate_events, "tagged_kinds", lambda _tag: published)
    findings, note = gate_events.check_append_only()
    assert note == "FAIL against v0.1.0"
    assert len(findings) == 1
    assert "cache.warm was published by v0.1.0 and is gone" in findings[0].headline
    assert "never removed" in findings[0].render()


def test_a_reordered_published_prefix_is_a_finding(monkeypatch: pytest.MonkeyPatch) -> None:
    current = gate_events.kinds_in(EVENTS_PATH)
    published = (current[1], current[0], *current[2:10])
    monkeypatch.setattr(gate_events, "previous_tag", lambda: "v0.1.0")
    monkeypatch.setattr(gate_events, "tagged_kinds", lambda _tag: published)
    findings, _note = gate_events.check_append_only()
    assert len(findings) == 1
    assert "moved within the published prefix" in findings[0].headline


def test_an_appended_row_passes_the_append_only_check(monkeypatch: pytest.MonkeyPatch) -> None:
    """The positive case: a shorter published prefix is exactly what an append looks like."""
    published = gate_events.kinds_in(EVENTS_PATH)[:59]
    monkeypatch.setattr(gate_events, "previous_tag", lambda: "v0.1.0")
    monkeypatch.setattr(gate_events, "tagged_kinds", lambda _tag: published)
    findings, note = gate_events.check_append_only()
    assert findings == ()
    assert note == "ok against v0.1.0: 59 published, 6 appended"


def test_a_tag_that_carries_no_events_file_skips(monkeypatch: pytest.MonkeyPatch) -> None:
    """This cell IS that change, so the first tag after it is the first with anything to compare."""
    monkeypatch.setattr(gate_events, "previous_tag", lambda: "v0.1.0")
    monkeypatch.setattr(gate_events, "tagged_kinds", lambda _tag: None)
    findings, note = gate_events.check_append_only()
    assert findings == ()
    assert note == "SKIP (v0.1.0 carries no tools/events.toml)"


def test_the_tagged_reader_survives_a_shape_this_version_does_not_expect() -> None:
    """The charter's rows carried no `level`; a history reader that assumed one would crash.

    `tagged_kinds` reads `kind` with an anchored line pattern for exactly this reason, so the check
    reports a finding rather than raising while looking at an older file.
    """
    old_shape = '[[event]]\nkind = "run.start"\nfields = ["trigger"]\n[[event]]\nkind = "degrade"\n'
    assert gate_events._KIND_RE.findall(old_shape) == ["run.start", "degrade"]


def test_the_gate_refuses_an_argument() -> None:
    assert gate_events.main(["--fix"]) == 2


def test_the_gates_register_names_this_script_as_g20s_runner() -> None:
    """`runner`, not `runner_planned`: the register's own forcing function, now discharged."""
    register = tomllib.loads((REPO / "tools" / "gates.toml").read_text(encoding="utf-8"))
    row = next(gate for gate in register["gate"] if gate["id"] == "G20")
    assert row["runner"] == ["tools/gate_events.py"]
    assert "runner_planned" not in row
    assert (REPO / "tools" / "gate_events.py").is_file()
