"""`ow out targets`: each compile card discovery finds, with its flag, its reason and enablement.

The cards are the shipped ones: `compile.text.owtext` from the conformance suite's directory on
`OMNIWEAVE_DRIVER_PATH`, and `compile.video.native` from its distribution's entry point. What is
under test is that the verb prints what the cards declare, so each expectation is read back from
`CompileCard.of()` where a card says it.
"""

from __future__ import annotations

import io
import json
import os
import shutil
from pathlib import Path
from typing import TYPE_CHECKING, Any

import omniweave.__main__ as launcher
import omniweave_conform.suites.target as target_suites
import pytest
from omniweave.surface import out as verb
from omniweave_core.discovery import discover
from omniweave_core.errors import UsageError
from omniweave_core.out.card import CompileCard

if TYPE_CHECKING:
    from collections.abc import Sequence

SUITES = Path(target_suites.__file__).parent
"""`<dir>/*/driver.toml`: the directory `owtext/` sits in."""

KEYS = [
    "target", "driver", "implemented", "enabled", "reason",
    "determinism", "carrier", "il", "fidelity", "laws",
]  # fmt: skip


def _env(home: Path, *paths: Path) -> dict[str, str]:
    env = {
        "OMNIWEAVE_HOME": str(home / "owhome"),
        "HOME": str(home / "home"),
        "USERPROFILE": str(home / "home"),
    }
    if paths:
        env["OMNIWEAVE_DRIVER_PATH"] = os.pathsep.join(str(p) for p in paths)
    return env


def _run(argv: Sequence[str], cwd: Path, env: dict[str, str]) -> tuple[int, str, str]:
    out, err = io.StringIO(), io.StringIO()
    code = verb.main(["out", "targets", *argv], cwd=cwd, env=env, stdout=out, stderr=err)
    return code, out.getvalue(), err.getvalue()


def _rows(cwd: Path, env: dict[str, str]) -> dict[str, dict[str, Any]]:
    code, out, err = _run(["--render", "json"], cwd, env)
    assert (code, err) == (0, "")
    document = json.loads(out)
    assert isinstance(document, list)
    return {row["target"]: row for row in document}


def _card(target: str, env: dict[str, str]) -> CompileCard:
    for card in discover(env=env).cards:
        if str(card.identity.port) == "compile":
            compiled = CompileCard.of(card)
            if compiled.target == target:
                return compiled
    raise AssertionError(target)


# ---------------------------------------------------------------------------------------------
# Ruling 2: the bare array 16-roadmap's P9 exit criterion reads
# ---------------------------------------------------------------------------------------------


def test_render_json_is_a_bare_array_and_video_is_listed_unimplemented(tmp_path: Path) -> None:
    """16's P9 exit: `ow out targets --render json | jq '.[] | select(.target=="video")
    | .implemented == false'`."""
    env = _env(tmp_path, SUITES)
    rows = _rows(tmp_path, env)
    assert sorted(rows) == ["owtext", "video"]
    video = rows["video"]
    assert video["implemented"] is False
    assert video["reason"] == _card("video", env).reason
    assert video["reason"].strip()
    assert video["driver"] == "compile.video.native"
    owtext = rows["owtext"]
    assert (owtext["implemented"], owtext["reason"]) == (True, "")
    assert owtext["driver"] == "compile.text.owtext"


def test_a_row_carries_the_cards_determinism_class_and_the_ten_keys_in_order(
    tmp_path: Path,
) -> None:
    """10's roster: *"which artefact kinds this deployment can compile, and their determinism
    class"*."""
    env = _env(tmp_path, SUITES)
    rows = _rows(tmp_path, env)
    for target, row in rows.items():
        card = _card(target, env)
        assert list(row) == KEYS
        assert row["determinism"] == list(card.determinism)
        assert (row["carrier"], row["il"], row["fidelity"]) == (
            card.carrier,
            card.il,
            card.fidelity,
        )
        assert row["laws"] == list(card.laws)
    assert rows["owtext"]["determinism"] == ["part", "byte"]


def test_without_the_suite_on_the_path_only_the_installed_video_card_is_listed(
    tmp_path: Path,
) -> None:
    assert sorted(_rows(tmp_path, _env(tmp_path))) == ["video"]


# ---------------------------------------------------------------------------------------------
# Ruling 1: implemented and enabled, each named when it is the one missing
# ---------------------------------------------------------------------------------------------


def test_enabled_is_whether_targets_enabled_lists_the_kind(tmp_path: Path) -> None:
    """The default `[targets] enabled` is `["pptx"]`, so neither shipped kind is enabled."""
    env = _env(tmp_path, SUITES)
    assert {t: r["enabled"] for t, r in _rows(tmp_path, env).items()} == {
        "owtext": False,
        "video": False,
    }
    (tmp_path / "omniweave.toml").write_text(
        '[targets]\nenabled = ["owtext", "video"]\n', encoding="utf-8"
    )
    assert {t: r["enabled"] for t, r in _rows(tmp_path, env).items()} == {
        "owtext": True,
        "video": True,
    }


def test_config_names_the_file_enabled_is_read_from(tmp_path: Path) -> None:
    other = tmp_path / "elsewhere.toml"
    other.write_text('[targets]\nenabled = ["owtext"]\n', encoding="utf-8")
    env = _env(tmp_path, SUITES)
    code, out, err = _run(["--render", "json", "--config", str(other)], tmp_path, env)
    assert (code, err) == (0, "")
    assert {r["target"]: r["enabled"] for r in json.loads(out)} == {
        "owtext": True,
        "video": False,
    }


def test_the_text_form_says_which_of_the_two_stops_a_kind(tmp_path: Path) -> None:
    (tmp_path / "omniweave.toml").write_text('[targets]\nenabled = ["video"]\n', encoding="utf-8")
    env = _env(tmp_path, SUITES)
    code, out, err = _run([], tmp_path, env)
    assert (code, err) == (0, "")
    owtext, video = out.splitlines()
    assert owtext.startswith("owtext   not ready compile.text.owtext")
    assert owtext.endswith("not in [targets] enabled")
    assert "html/owtext" in owtext
    assert "determinism part+byte" in owtext
    #  Enabled and still not ready: the card's reason is what stops it.
    assert video.startswith("video    not ready compile.video.native")
    assert video.endswith(f"implemented = false: {_card('video', env).reason}")
    (tmp_path / "omniweave.toml").write_text('[targets]\nenabled = ["owtext"]\n', encoding="utf-8")
    assert _run([], tmp_path, env)[1].splitlines()[0].split()[1:3] == [
        "ready",
        "compile.text.owtext",
    ]


def test_a_driver_vendored_into_the_project_is_listed(tmp_path: Path) -> None:
    """`.omniweave/drivers/<name>/`, found from the `omniweave.toml` that supplied a value."""
    shutil.copytree(
        SUITES / "owtext",
        tmp_path / ".omniweave" / "drivers" / "owtext",
        ignore=shutil.ignore_patterns("__pycache__"),
    )
    (tmp_path / "omniweave.toml").write_text('[targets]\nenabled = ["owtext"]\n', encoding="utf-8")
    rows = _rows(tmp_path, _env(tmp_path))
    assert sorted(rows) == ["owtext", "video"]
    assert rows["owtext"]["enabled"] is True


# ---------------------------------------------------------------------------------------------
# Ruling 3: a refused card is a count on stderr, never a row
# ---------------------------------------------------------------------------------------------


def test_a_card_discovery_refuses_is_counted_on_stderr_and_not_listed(tmp_path: Path) -> None:
    broken = tmp_path / "broken" / "nonsense"
    broken.mkdir(parents=True)
    (broken / "driver.toml").write_text("card_schema = 1\n[driver\n", encoding="utf-8")
    env = _env(tmp_path, SUITES, tmp_path / "broken")
    code, out, err = _run(["--render", "json"], tmp_path, env)
    assert code == 0
    assert sorted(r["target"] for r in json.loads(out)) == ["owtext", "video"]
    assert err == "ow out targets: 1 card(s) were refused; `ow doctor` names each\n"


def test_no_compile_card_at_all_is_one_line_naming_doctor(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(verb, "targets_report", lambda **_: (verb.TargetsReport(()), 0))
    code, out, err = _run([], tmp_path, _env(tmp_path))
    assert (code, err) == (0, "")
    assert out == "no compile card was found; `ow doctor` lists what discovery saw\n"
    code, out, _ = _run(["--render", "json"], tmp_path, _env(tmp_path))
    assert (code, json.loads(out)) == (0, [])


# ---------------------------------------------------------------------------------------------
# Ruling 4: the flags this verb has no writer for
# ---------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("argv", "named"),
    [
        (["--quiet"], "--quiet"),
        (["--render", "jsonl"], "--render jsonl"),
        (["--render", "rows"], "--render rows"),
    ],
)
def test_quiet_and_the_row_renders_are_refused_by_name(
    argv: list[str], named: str, tmp_path: Path
) -> None:
    code, out, err = _run(argv, tmp_path, _env(tmp_path, SUITES))
    assert code == UsageError.EXIT
    assert out == ""
    assert f"{named} is parsed and not served by ow out targets" in err
    assert "fix: ow out targets [--render json]" in err


def test_a_refusal_under_render_json_is_10_1539s_object(tmp_path: Path) -> None:
    code, out, err = _run(["--render", "json", "--quiet"], tmp_path, _env(tmp_path))
    assert (code, err) == (UsageError.EXIT, "")
    assert json.loads(out)["error"]["message"].startswith("--quiet is parsed and not served")


def test_corpus_is_inert_and_verbose_is_refused(tmp_path: Path) -> None:
    env = _env(tmp_path, SUITES)
    code, out, _ = _run(["--render", "json", "--corpus", "handbook"], tmp_path, env)
    assert code == 0
    assert sorted(r["target"] for r in json.loads(out)) == ["owtext", "video"]
    code, _, err = _run(["-v"], tmp_path, env)
    assert code == UsageError.EXIT
    assert "--verbose is parsed and not served by ow out" in err


def test_an_unrostered_out_verb_never_parses(tmp_path: Path) -> None:
    """Ruling 5: `ow out compile` has no Action, so the generated tree has no node for it."""
    out, err = io.StringIO(), io.StringIO()
    code = verb.main(["out", "compile"], cwd=tmp_path, env=_env(tmp_path), stdout=out, stderr=err)
    assert code != 0
    assert out.getvalue() == ""


# ---------------------------------------------------------------------------------------------
# The console script routes `out`
# ---------------------------------------------------------------------------------------------


def test_the_console_script_routes_out_to_this_verb(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.chdir(tmp_path)
    for key, value in _env(tmp_path, SUITES).items():
        monkeypatch.setenv(key, value)
    assert "out" in launcher.DISPATCHED
    code = launcher.main(["out", "targets", "--render", "json"])
    captured = capsys.readouterr()
    assert (code, captured.err) == (0, "")
    [video] = [r for r in json.loads(captured.out) if r["target"] == "video"]
    assert video["implemented"] is False
