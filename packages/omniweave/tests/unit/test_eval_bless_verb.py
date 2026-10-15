"""`ow eval bless --inventory --reason TEXT`: the verb, and each exit its docstring rules. D846.

The verb runs in-process through `omniweave.surface.eval.main`, with the entry point replaced, so
this file holds what the CLI side owns:
- the refusals before anything is called;
- what is handed across;
- the two renderings;
- the reply's shape.

`test_conform_inventory.py` holds the bless itself, collected for real.
"""

from __future__ import annotations

import io
import json
from pathlib import Path
from typing import Any

import omniweave.__main__ as launcher
import pytest
from omniweave.surface import dispatch
from omniweave.surface import eval as verb
from omniweave_core.errors import QualityError

REASON = "retire the stub driver's tests with the stub itself"
COUNTS = "incidental=0,structural=1,unexplained=0"
ROW = f"2026-10-15\tq@example.org\teval/inventory.toml\t{COUNTS}\t{REASON}"
REPLY: dict[str, Any] = {
    "inventory": "eval/inventory.toml",
    "log": "eval/BLESS.log",
    "row": ROW,
    "fell": ["omniweave-x/unit: tests 5 -> 2"],
    "changed": ["omniweave-x/unit"],
    "tests": 2,
}


@pytest.fixture
def seen(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    calls: dict[str, Any] = {}

    def entry(**kwargs: Any) -> dict[str, Any]:
        calls.update(kwargs)
        return REPLY

    monkeypatch.setattr(verb, "eval_entry", lambda name: entry if name == "bless" else None)
    monkeypatch.setattr(verb, "_today", lambda: "2026-10-15")
    return calls


def _run(cwd: Path, *argv: str, env: dict[str, str] | None = None) -> tuple[int, str, str]:
    out, err = io.StringIO(), io.StringIO()
    code = verb.main(
        ["eval", "bless", *argv],
        cwd=cwd,
        env=env or {"OMNIWEAVE_BLESS": "1"},
        stdout=out,
        stderr=err,
    )
    return code, out.getvalue(), err.getvalue()


def test_a_bless_prints_what_fell_the_row_and_one_verdict(
    tmp_path: Path, seen: dict[str, Any]
) -> None:
    assert _run(tmp_path, "--inventory", "--reason", REASON) == (
        0,
        "  fell     omniweave-x/unit: tests 5 -> 2\n"
        f"  row      {ROW}\n"
        "blessed eval/inventory.toml: 1 area(s) moved, 1 fell, 2 test(s); wrote "
        "eval/inventory.toml and a row in eval/BLESS.log\n",
        "",
    )
    assert seen == {
        "root": str(tmp_path),
        "reason": REASON,
        "date": "2026-10-15",
        "env": {"OMNIWEAVE_BLESS": "1"},
    }


def test_render_json_prints_one_object(tmp_path: Path, seen: dict[str, Any]) -> None:
    code, out, _ = _run(tmp_path, "--inventory", "--reason", REASON, "--render", "json")
    assert code == 0
    assert json.loads(out) == REPLY
    assert seen["reason"] == REASON


@pytest.mark.parametrize(
    ("argv", "message"),
    [
        (("--inventory", "--counters", "--reason", REASON), "--counters is parsed and not served"),
        (("--reason", REASON), "ow eval bless needs --inventory"),
        (("--inventory",), "ow eval bless needs --reason"),
        (("--inventory", "--reason", REASON, "--render", "jsonl"), "--render jsonl is parsed"),
        (("--inventory", "--reason", REASON, "--render", "rows"), "--render rows is parsed"),
    ],
)
def test_each_refusal_comes_before_anything_is_called(
    tmp_path: Path, seen: dict[str, Any], argv: tuple[str, ...], message: str
) -> None:
    code, _, err = _run(tmp_path, *argv)
    assert code == 1
    assert message in err
    assert "OMNIWEAVE_BLESS=1 ow eval bless --inventory --reason '<why>'" in err
    assert seen == {}


def test_a_refused_bless_exits_1_with_its_quality_code(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def refuse(**_: Any) -> dict[str, Any]:
        raise QualityError("nothing to bless: no area's tests or properties fell", fix="x")

    monkeypatch.setattr(verb, "eval_entry", lambda _name: refuse)
    code, out, err = _run(tmp_path, "--inventory", "--reason", REASON)
    assert (code, out) == (1, "")
    assert "OW_QUALITY" in err
    assert "nothing to bless" in err


@pytest.mark.parametrize(
    "reply",
    [
        {},
        {**REPLY, "row": 1},
        {**REPLY, "fell": "x"},
        {**REPLY, "changed": [1]},
        {**REPLY, "tests": "2"},
        {**REPLY, "inventory": None},
    ],
)
def test_a_malformed_reply_is_an_internal_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, reply: dict[str, Any]
) -> None:
    monkeypatch.setattr(verb, "eval_entry", lambda _name: lambda **_: reply)
    monkeypatch.setattr(verb, "_today", lambda: "2026-10-15")
    code, _, err = _run(tmp_path, "--inventory", "--reason", REASON)
    assert code == 70
    assert "bless entry point returned no inventory, log, row, fell, changed and tests" in err


def test_today_is_a_utc_iso_date() -> None:
    today = verb._today()
    assert len(today) == 10
    assert today[4] == today[7] == "-"


def test_the_launcher_routes_bless_to_the_verb(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.chdir(tmp_path)
    assert launcher.main(["eval", "bless", "--inventory"]) == 1
    assert "ow eval bless needs --reason" in capsys.readouterr().err


def test_the_workspace_installs_the_bless_entry_point() -> None:
    from omniweave_conform.entry import bless  # noqa: PLC0415

    assert dispatch.eval_entry("bless") is bless
