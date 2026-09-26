"""`ow surface emit [--check | --bless]`: G25's step as a verb, dispatched (D334).

The green case is the real one and it is first: `ow surface emit --check` on this repository exits
0. The rest pin the verb's own rules over `gen.emit`'s two halves, patched, so a finding and a write
can be shown without making the tree dirty.
"""

from __future__ import annotations

import io

import omniweave.__main__ as launcher
import pytest
from omniweave.cli import ACTION_DEST, build_parser
from omniweave.gen import emit, verb


def _run(argv: list[str]) -> tuple[int, str, str]:
    out, err = io.StringIO(), io.StringIO()
    code = verb.main(argv, stdout=out, stderr=err)
    return code, out.getvalue(), err.getvalue()


def test_ow_surface_emit_check_is_green_on_this_repository() -> None:
    """G25, through the verb that six generated headers and `tools/gates.toml` name."""
    code, out, err = _run(["surface", "emit", "--check"])
    assert (code, err) == (verb.OK, "")
    assert out == "surface emit --check: every generated artefact matches ACTIONS\n"


def test_drift_is_exit_1_and_every_finding_is_printed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(emit, "check", lambda: ("llms.txt: differs", "docs/AGENTS.md: differs"))
    monkeypatch.setattr(
        emit, "emit", lambda: pytest.fail("--check wrote: it would repair its gate")
    )
    code, out, _ = _run(["surface", "emit", "--check"])
    assert code == verb.DRIFT
    assert out.splitlines() == [
        "llms.txt: differs",
        "docs/AGENTS.md: differs",
        "surface emit --check: 2 finding(s); run ow surface emit",
    ]


def test_a_write_reports_each_path_it_changed_and_bless_is_the_same_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """11:486 via `emit()`'s docstring: blessing is the reviewable diff, not a second mechanism."""
    calls: list[str] = []

    def fake() -> tuple[str, ...]:
        calls.append("emit")
        return ("llms.txt",)

    monkeypatch.setattr(emit, "emit", fake)
    for flags in ([], ["--bless"]):
        code, out, _ = _run(["surface", "emit", *flags])
        assert code == verb.OK
        assert out.splitlines() == ["wrote llms.txt", "surface emit: 1 artefact(s) changed"]
    assert calls == ["emit", "emit"]


def test_check_and_bless_together_are_refused_and_nothing_is_written(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A check that also wrote would repair the thing it measures."""
    monkeypatch.setattr(emit, "emit", lambda: pytest.fail("a refused call wrote"))
    code, out, err = _run(["surface", "emit", "--check", "--bless"])
    assert code == 2
    assert out == ""
    assert "--check or --bless, not both" in err


def test_the_verb_is_in_the_generated_tree_and_dispatched_by_the_launcher() -> None:
    """D334's two halves: the row puts `surface emit` in the parser, and `__main__` routes it."""
    parsed = build_parser().parse_args(["surface", "emit", "--check"])
    assert getattr(parsed, ACTION_DEST) == "surface.emit"
    assert parsed.check is True
    assert "surface" in launcher.DISPATCHED
